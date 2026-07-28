"""Strict legacy workspace discovery and migration inventory."""

from __future__ import annotations

import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

from ledgercore.hashing import sha256_bytes, sha256_text
from ledgercore.jsonio import canonical_json

from documentledger.errors import DocumentledgerError
from documentledger.identity import doc_record_filename, normalize_repo_path
from documentledger.models import Config
from documentledger.source_index import source_inventory
from documentledger.storage import (
    DOC_RECORD_SCHEMA,
    SCAN_SCHEMA,
    SOURCE_INDEX_FILENAME,
    SOURCE_INDEX_SCHEMA,
    normalize_source_index_payload,
    read_json,
    read_yaml,
    source_index_payload,
    validate_storage_metadata,
)

LEGACY_CONFIG_NAMES = ("documentledger.toml", ".documentledger.toml")
FORBIDDEN_TIMESTAMP_KEYS = {f"{prefix}_at" for prefix in ("created", "updated", "generated")}


@dataclass(frozen=True, slots=True)
class LegacyProject:
    root: Path
    config_path: Path
    data_dir: Path
    config: Config
    raw: dict[str, Any]


@dataclass(frozen=True, slots=True)
class InventoryFile:
    relative_path: str
    category: str
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class LegacyInventory:
    files: tuple[InventoryFile, ...]
    authoritative: tuple[InventoryFile, ...]
    derived: tuple[InventoryFile, ...]
    provisional: tuple[InventoryFile, ...]
    unknown: tuple[InventoryFile, ...]
    digest: str

    @property
    def bytes(self) -> int:
        return sum(item.size for item in self.files)


def find_legacy_config(start: Path | None = None) -> Path | None:
    current = (start or Path.cwd()).resolve()
    while True:
        for name in LEGACY_CONFIG_NAMES:
            path = current / name
            if path.is_file() and not path.is_symlink():
                return path
        if current.parent == current:
            return None
        current = current.parent


def _strings(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise DocumentledgerError("invalid_legacy_config", f"{field} must be an array of strings.")
    return list(value)


def load_legacy_project(path: Path) -> LegacyProject:
    """Parse the permissive-era config with migration-only strict rules."""
    try:
        raw = dict(tomllib.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        raise DocumentledgerError("invalid_legacy_config", f"Unable to read legacy config {path}: {exc}") from exc
    allowed = {"ledger", "project", "storage", "scan", "validation", "policy"}
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise DocumentledgerError("invalid_legacy_config", f"Legacy config contains unsupported table(s): {', '.join(unknown)}.")
    root = path.parent.resolve()
    ledger = raw.get("ledger", {})
    project = raw.get("project", {})
    storage = raw.get("storage", {})
    scan = raw.get("scan", {})
    validation = raw.get("validation", {})
    policy = raw.get("policy", {})
    for name, value in (
        ("ledger", ledger),
        ("project", project),
        ("storage", storage),
        ("scan", scan),
        ("validation", validation),
        ("policy", policy),
    ):
        if not isinstance(value, dict):
            raise DocumentledgerError("invalid_legacy_config", f"{name} must be a TOML table.")
    if not isinstance(ledger.get("code", "dl"), str) or not ledger.get("code", "dl"):
        raise DocumentledgerError("invalid_legacy_config", "ledger.code must be a non-empty string.")
    for key in ("source_roots", "doc_roots", "source_extensions", "doc_extensions"):
        _strings(scan.get(key, []), f"scan.{key}")
    _strings(validation.get("commands", []), "validation.commands")
    if not isinstance(policy.get("require_doc_frontmatter", False), bool):
        raise DocumentledgerError("invalid_legacy_config", "policy.require_doc_frontmatter must be boolean.")
    legacy_uuid = project.get("uuid", "")
    if legacy_uuid:
        try:
            legacy_uuid = str(UUID(str(legacy_uuid)))
        except ValueError as exc:
            raise DocumentledgerError("invalid_legacy_config", "project.uuid must be a valid UUID.") from exc
    storage_value = storage.get("documentledger_dir", ".documentledger")
    if not isinstance(storage_value, str) or not storage_value:
        raise DocumentledgerError("invalid_legacy_config", "storage.documentledger_dir must be a non-empty string.")
    data_dir = Path(storage_value)
    if not data_dir.is_absolute():
        data_dir = (root / data_dir).resolve()
    if data_dir == root or root in data_dir.parents and data_dir.name == ".ledger":
        raise DocumentledgerError("invalid_legacy_root", "Legacy storage root is not a safe independent data directory.")
    config = Config(
        root=root,
        path=path.resolve(),
        project_name=str(project.get("name") or root.name),
        project_uuid=str(legacy_uuid),
        storage_dir=data_dir,
        source_roots=_strings(scan.get("source_roots", []), "scan.source_roots"),
        doc_roots=_strings(scan.get("doc_roots", []), "scan.doc_roots"),
        source_extensions=_strings(scan.get("source_extensions", []), "scan.source_extensions"),
        doc_extensions=_strings(scan.get("doc_extensions", []), "scan.doc_extensions"),
        validation_commands=_strings(validation.get("commands", []), "validation.commands"),
        require_doc_frontmatter=bool(policy.get("require_doc_frontmatter", False)),
    )
    return LegacyProject(root=root, config_path=path.resolve(), data_dir=data_dir, config=config, raw=raw)


def _walk_regular_files(root: Path) -> list[Path]:
    if not root.exists() or not root.is_dir() or root.is_symlink():
        raise DocumentledgerError("legacy_storage_missing", f"Legacy data directory is missing or invalid: {root}")
    result: list[Path] = []
    for path in sorted(root.rglob("*")):
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise DocumentledgerError("legacy_symlink_unsupported", f"Legacy migration refuses symlink: {path}")
        if stat.S_ISREG(info.st_mode):
            result.append(path)
        elif not stat.S_ISDIR(info.st_mode):
            raise DocumentledgerError("legacy_special_file", f"Legacy migration refuses special file: {path}")
    return result


def inventory_legacy_data(project: LegacyProject) -> LegacyInventory:
    records: list[InventoryFile] = []
    for path in _walk_regular_files(project.data_dir):
        rel = path.relative_to(project.data_dir).as_posix()
        if rel == ".ledger-project.toml":
            category = "unknown"
        elif rel in {"storage.yaml", "scan.yaml", SOURCE_INDEX_FILENAME} or rel.startswith("docs/"):
            category = "authoritative"
        elif rel == "rendered" or rel.startswith("rendered/"):
            category = "derived"
        elif rel == "proposals" or rel.startswith("proposals/"):
            category = "provisional"
        else:
            category = "unknown"
        records.append(InventoryFile(rel, category, path.stat().st_size, sha256_bytes(path.read_bytes())))
    digest = sha256_text(
        canonical_json(
            [{"relative_path": item.relative_path, "category": item.category, "size": item.size, "sha256": item.sha256} for item in records]
        )
    )
    return LegacyInventory(
        files=tuple(records),
        authoritative=tuple(item for item in records if item.category == "authoritative"),
        derived=tuple(item for item in records if item.category == "derived"),
        provisional=tuple(item for item in records if item.category == "provisional"),
        unknown=tuple(item for item in records if item.category == "unknown"),
        digest=digest,
    )


def _check_no_timestamps(value: Any, path: str) -> None:
    if isinstance(value, dict):
        forbidden = FORBIDDEN_TIMESTAMP_KEYS & set(value)
        if forbidden:
            raise DocumentledgerError(
                "legacy_timestamp_field", f"{path} contains forbidden timestamp field(s): {', '.join(sorted(forbidden))}."
            )
        for key, child in value.items():
            _check_no_timestamps(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _check_no_timestamps(child, f"{path}[{index}]")


def validate_legacy_state(project: LegacyProject, inventory: LegacyInventory) -> dict[str, Any]:
    metadata_path = project.data_dir / "storage.yaml"
    metadata = validate_storage_metadata(read_yaml(metadata_path))
    _check_no_timestamps(metadata, str(metadata_path))
    storage_uuid = str(metadata["project_uuid"])
    if project.config.project_uuid and project.config.project_uuid != storage_uuid:
        raise DocumentledgerError("project_uuid_mismatch", "Legacy config and storage.yaml project UUIDs differ.")
    scan_path = project.data_dir / "scan.yaml"
    scan: dict[str, Any] | None = None
    if scan_path.exists():
        scan = read_yaml(scan_path)
        _check_no_timestamps(scan, str(scan_path))
        if scan.get("schema") != SCAN_SCHEMA:
            raise DocumentledgerError("schema_mismatch", f"scan.yaml schema must be {SCAN_SCHEMA}.")
        if int(scan.get("version", 0)) <= 0:
            raise DocumentledgerError("invalid_scan_state", "scan.yaml version must be positive.")
    index_path = project.data_dir / SOURCE_INDEX_FILENAME
    index: dict[str, Any] | None = None
    if index_path.exists():
        index = read_json(index_path)
        _check_no_timestamps(index, str(index_path))
        if index.get("schema") != SOURCE_INDEX_SCHEMA:
            raise DocumentledgerError("schema_mismatch", f"source-index.json schema must be {SOURCE_INDEX_SCHEMA}.")
        normalize_source_index_payload(index)
        if scan and str(scan.get("source_index_hash", metadata.get("last_scan_source_index_hash", ""))):
            expected = str(scan.get("source_index_hash") or metadata.get("last_scan_source_index_hash") or "")
            actual = sha256_text(canonical_json(index))
            if expected and expected != actual:
                raise DocumentledgerError(
                    "source_index_hash_mismatch", f"source-index.json hash mismatch: expected {expected}, got {actual}."
                )
    needs_index = int(metadata.get("last_scan_version", 0)) > 0
    if needs_index and scan is None:
        raise DocumentledgerError("invalid_scan_state", "storage metadata references a scan but scan.yaml is missing.")
    repairable = False
    expected_hash = str((scan or {}).get("source_index_hash") or metadata.get("last_scan_source_index_hash") or "")
    if needs_index and index is None and expected_hash:
        source_paths = sorted(dict((scan or {}).get("source_hashes", {})))
        try:
            current = {path: sha256_bytes((project.root / path).read_bytes()) for path in source_paths}
            repairable = all(current[path] == str((scan or {}).get("source_hashes", {})[path]) for path in source_paths)
            if repairable:
                generated = source_index_payload(source_inventory(project.root, source_paths))
                repairable = sha256_text(canonical_json(generated)) == expected_hash
        except (OSError, DocumentledgerError):
            repairable = False
    for item in inventory.authoritative:
        if item.relative_path.startswith("docs/") and item.relative_path.endswith(".yaml"):
            record = read_yaml(project.data_dir / item.relative_path)
            _check_no_timestamps(record, item.relative_path)
            if record.get("schema") != DOC_RECORD_SCHEMA:
                raise DocumentledgerError("schema_mismatch", f"Document record {item.relative_path} has an incompatible schema.")
            doc_path = normalize_repo_path(str(record.get("doc_path", "")))
            if doc_record_filename(doc_path) != Path(item.relative_path).name:
                raise DocumentledgerError("invalid_doc_record", f"Document record filename does not match doc_path: {item.relative_path}")
    return {
        "metadata": metadata,
        "scan": scan,
        "source_index": index,
        "source_index_present": index is not None,
        "source_index_repairable": repairable,
        "source_index_expected_hash": expected_hash,
    }
