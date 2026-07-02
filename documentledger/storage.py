from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Literal, overload

from ledgercore.atomic import atomic_create_text
from ledgercore.errors import AtomicWriteError, LedgerCoreError, YamlStoreError
from ledgercore.paths import locate_config
from ledgercore.yamlio import load_yaml_object
from ledgercore.yamlio import write_yaml as core_write_yaml

try:
    import tomllib  # type: ignore[import-not-found]
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[import-not-found,no-redef]

from documentledger.doc_index import doc_sections_for_file, whole_doc_section
from documentledger.errors import DocumentledgerError
from documentledger.identity import doc_record_filename, normalize_repo_path
from documentledger.models import Config, Workspace
from documentledger.source_index import file_unit_id

CONFIG_NAMES = ("documentledger.toml", ".documentledger.toml")
STORAGE_SCHEMA_VERSION = 4
SCAN_SCHEMA = "documentledger.scan.v4"
DOC_RECORD_SCHEMA = "documentledger.doc_record.v4"
SCAN_FILENAME = "scan.yaml"
TIMESTAMP_KEYS = {f"{prefix}_at" for prefix in ("created", "updated", "generated")}
DEFAULT_CONFIG = {
    "ledger": {"code": "dl", "name": "documentledger"},
    "scan": {
        "source_roots": ["documentledger", "tests"],
        "doc_roots": ["docs", "README.md"],
        "source_extensions": [".py"],
        "doc_extensions": [".md", ".rst"],
    },
    "validation": {"commands": []},
    "policy": {"require_doc_frontmatter": False},
}


def coerce_int(value: object, default: int) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return default


def strip_timestamp_keys(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key not in TIMESTAMP_KEYS}


def read_yaml(path: Path) -> dict[str, Any]:
    try:
        return dict(load_yaml_object(path, label=str(path)))
    except YamlStoreError as exc:
        raise DocumentledgerError("invalid_yaml", f"Invalid YAML in {path}: {exc}") from exc


def write_yaml(path: Path, data: dict[str, Any]) -> None:
    try:
        core_write_yaml(path, data, sort_keys=False)
    except LedgerCoreError as exc:
        raise DocumentledgerError("storage_write_failed", f"Failed to write {path}: {exc}") from exc


def discover_config(start: Path | None = None) -> Path | None:
    locator = locate_config(start or Path.cwd(), CONFIG_NAMES)
    return locator.config_path if locator else None


def load_config(path: Path) -> Config:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    storage_data = data.get("storage", {})
    project_data = data.get("project", {})
    scan_data = DEFAULT_CONFIG["scan"] | data.get("scan", {})
    validation_data = DEFAULT_CONFIG["validation"] | data.get("validation", {})
    policy_data = DEFAULT_CONFIG["policy"] | data.get("policy", {})
    root = path.parent.resolve()
    storage_value = storage_data.get("documentledger_dir", ".documentledger")
    storage_dir = Path(storage_value)
    if not storage_dir.is_absolute():
        storage_dir = root / storage_dir
    return Config(
        root=root,
        path=path,
        project_name=str(project_data.get("name", root.name)),
        project_uuid=str(project_data.get("uuid", "")),
        storage_dir=storage_dir,
        source_roots=list(scan_data.get("source_roots", [])),
        doc_roots=list(scan_data.get("doc_roots", [])),
        source_extensions=list(scan_data.get("source_extensions", [".py"])),
        doc_extensions=list(scan_data.get("doc_extensions", [".md", ".rst"])),
        validation_commands=list(validation_data.get("commands", [])),
        require_doc_frontmatter=bool(policy_data.get("require_doc_frontmatter", False)),
    )


@overload
def load_workspace(required: Literal[True] = True) -> Workspace: ...


@overload
def load_workspace(required: Literal[False]) -> Workspace | None: ...


def load_workspace(required: bool = True) -> Workspace | None:
    config_path = discover_config()
    if config_path is None:
        if required:
            raise DocumentledgerError(
                "workspace_not_found",
                "No documentledger.toml or .documentledger.toml found.",
                ["Run `docledger init` from the project root."],
            )
        return None
    config = load_config(config_path)
    metadata_path = config.storage_dir / "storage.yaml"
    if not metadata_path.exists():
        if required:
            raise DocumentledgerError("storage_missing", "Documentledger storage metadata is missing.")
        metadata: dict[str, Any] = {}
    else:
        metadata = read_yaml(metadata_path)
    workspace = Workspace(config=config, metadata=metadata)
    if metadata_path.exists():
        migrate_workspace_state(workspace)
    return workspace


def init_workspace(project_name: str | None, documentledger_dir: str, hidden_config: bool) -> Workspace:
    root = Path.cwd().resolve()
    config_path = root / (".documentledger.toml" if hidden_config else "documentledger.toml")
    if any((root / name).exists() for name in CONFIG_NAMES):
        raise DocumentledgerError("already_initialized", "Documentledger is already initialized.")
    project_uuid = str(uuid.uuid4())
    name = project_name or root.name
    config_text = (
        '[ledger]\ncode = "dl"\nname = "documentledger"\n\n'
        f'[project]\nname = "{name}"\nuuid = "{project_uuid}"\n\n'
        f'[storage]\ndocumentledger_dir = "{documentledger_dir}"\n\n'
        '[scan]\nsource_roots = ["documentledger", "tests"]\n'
        'doc_roots = ["docs", "README.md"]\nsource_extensions = [".py"]\n'
        'doc_extensions = [".md", ".rst"]\n\n[validation]\ncommands = []\n\n'
        "[policy]\nrequire_doc_frontmatter = false\n"
    )
    try:
        atomic_create_text(config_path, config_text)
    except AtomicWriteError as exc:
        raise DocumentledgerError("already_initialized", "Documentledger is already initialized.") from exc
    config = load_config(config_path)
    metadata: dict[str, Any] = {
        "schema_version": STORAGE_SCHEMA_VERSION,
        "project_uuid": project_uuid,
        "state_version": 1,
    }
    for name_dir in ("docs", "rendered"):
        (config.storage_dir / name_dir).mkdir(parents=True, exist_ok=True)
    write_yaml(config.storage_dir / "storage.yaml", metadata)
    return Workspace(config=config, metadata=metadata)


def state_version(workspace: Workspace) -> int:
    return coerce_int(workspace.metadata.get("state_version"), 0)


def reserve_state_version(workspace: Workspace) -> int:
    version = state_version(workspace) + 1
    workspace.metadata["state_version"] = version
    return version


def save_metadata(workspace: Workspace) -> None:
    write_yaml(workspace.config.storage_dir / "storage.yaml", workspace.metadata)


def normalize_line_span(value: Any, default: tuple[int, int] = (1, 1)) -> list[int]:
    if isinstance(value, (list, tuple)) and len(value) == 2:
        start = coerce_int(value[0], default[0])
        end = coerce_int(value[1], max(start, default[1]))
        return [start, max(start, end)]
    return [default[0], default[1]]


def normalize_source_unit_record(source_id: str, record: dict[str, Any], fallback_path: str = "") -> dict[str, Any]:
    path = str(record.get("path") or fallback_path)
    hashes = {str(key): str(value) for key, value in dict(record.get("hashes", {})).items()}
    return {
        "source_id": source_id,
        "path": path,
        "kind": str(record.get("kind") or ("file" if source_id.startswith("py:file:") else "module")),
        "qualname": str(record.get("qualname") or path),
        "line_span": normalize_line_span(record.get("line_span")),
        "signature": str(record.get("signature") or path),
        "hashes": hashes,
    }


def normalize_changed_unit(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_id": str(record.get("source_id", "")),
        "path": str(record.get("path", "")),
        "kind": str(record.get("kind", "")),
        "qualname": str(record.get("qualname", "")),
        "change_type": str(record.get("change_type", "modified")),
        "changed_hashes": sorted(str(value) for value in (record.get("changed_hashes", []) or [])),
        "old_line_span": normalize_line_span(record.get("old_line_span")),
        "new_line_span": normalize_line_span(record.get("new_line_span")),
    }


def doc_sections_map(workspace: Workspace, doc_path: str) -> dict[str, dict[str, Any]]:
    target = workspace.config.root / doc_path
    if not target.exists():
        return {}
    return {section.section_id: section.to_record() | {"text": section.text} for section in doc_sections_for_file(target, doc_path)}


def normalize_section_link(record: dict[str, Any]) -> dict[str, Any]:
    tracked_hashes = {str(key): str(value) for key, value in dict(record.get("tracked_hashes", {})).items()}
    return {
        "source_id": str(record.get("source_id") or record.get("source_unit") or ""),
        "source_path": str(record.get("source_path") or record.get("path") or ""),
        "coverage": str(record.get("coverage") or "broad-file-fallback"),
        "impact": str(record.get("impact") or "unknown"),
        "reason": str(record.get("reason") or ""),
        "tracked_hashes": tracked_hashes,
    }


def normalize_doc_record(workspace: Workspace, record: dict[str, Any]) -> dict[str, Any]:
    normalized = strip_timestamp_keys(dict(record))
    doc_path = normalize_repo_path(str(normalized.get("doc_path", "")))
    indexed = doc_sections_map(workspace, doc_path)
    stored_sections = list(normalized.get("sections", []) or [])
    if not stored_sections:
        fallback = whole_doc_section(
            doc_path,
            (workspace.config.root / doc_path).read_text(encoding="utf-8") if (workspace.config.root / doc_path).exists() else "",
        ).to_record()
        fallback["links"] = []
        stored_sections = [fallback]
    sections: list[dict[str, Any]] = []
    for section in stored_sections:
        section_id = str(section.get("section_id") or "")
        indexed_section = dict(indexed.get(section_id, {}))
        base = indexed_section or {
            "section_id": section_id,
            "doc_path": doc_path,
            "heading_path": list(section.get("heading_path", []) or []),
            "heading_slug": str(section.get("heading_slug") or "whole-doc"),
            "line_span": normalize_line_span(section.get("line_span")),
            "section_hash": str(section.get("section_hash") or ""),
            "summary": str(section.get("summary") or ""),
        }
        base["links"] = [normalize_section_link(link) for link in (section.get("links", []) or [])]
        sections.append(base)
    linked_sources = sorted(
        {link["source_path"] for section in sections for link in (section.get("links", []) or []) if str(link.get("source_path", ""))}
    )
    return {
        "schema": DOC_RECORD_SCHEMA,
        "doc_path": doc_path,
        "linked_sources": linked_sources,
        "sections": sections,
        "last_fresh_scan_version": coerce_int(normalized.get("last_fresh_scan_version"), 0),
        "last_fresh_hash": str(normalized.get("last_fresh_hash") or ""),
        "notes": str(normalized.get("notes") or ""),
        "version": coerce_int(normalized.get("version"), 0),
    }


def normalize_scan_record(workspace: Workspace, record: dict[str, Any]) -> dict[str, Any]:
    normalized = strip_timestamp_keys(dict(record))
    source_hashes = {str(key): str(value) for key, value in dict(normalized.get("source_hashes", {})).items()}
    doc_hashes = {str(key): str(value) for key, value in dict(normalized.get("doc_hashes", {})).items()}
    raw_units = dict(normalized.get("source_units", {}))
    if not raw_units:
        raw_units = {
            file_unit_id(path): {
                "path": path,
                "kind": "file",
                "qualname": path,
                "line_span": [1, 1],
                "signature": path,
                "hashes": {
                    "file_hash": digest,
                    "signature_hash": digest,
                    "decorator_hash": digest,
                    "body_hash": digest,
                    "docstring_hash": digest,
                    "public_contract_hash": digest,
                    "content_hash": digest,
                },
            }
            for path, digest in source_hashes.items()
        }
    return {
        "schema": SCAN_SCHEMA,
        "version": coerce_int(normalized.get("version"), 0),
        "source_hashes": source_hashes,
        "doc_hashes": doc_hashes,
        "source_units": {
            source_id: normalize_source_unit_record(str(source_id), dict(data), str(data.get("path") or ""))
            for source_id, data in raw_units.items()
        },
        "changed_sources": sorted(str(value) for value in (normalized.get("changed_sources", []) or [])),
        "deleted_sources": sorted(str(value) for value in (normalized.get("deleted_sources", []) or [])),
        "changed_units": [normalize_changed_unit(dict(item)) for item in (normalized.get("changed_units", []) or [])],
        "added_units": [normalize_changed_unit(dict(item)) for item in (normalized.get("added_units", []) or [])],
        "deleted_units": [normalize_changed_unit(dict(item)) for item in (normalized.get("deleted_units", []) or [])],
        "affected_sections": list(normalized.get("affected_sections", []) or []),
        "stale_docs": sorted(str(value) for value in (normalized.get("stale_docs", []) or [])),
        "unlinked_changed_sources": sorted(str(value) for value in (normalized.get("unlinked_changed_sources", []) or [])),
        "unmapped_changed_units": list(normalized.get("unmapped_changed_units", []) or []),
    }


def scan_record_path(workspace: Workspace) -> Path:
    return workspace.config.storage_dir / SCAN_FILENAME


def save_scan(workspace: Workspace, scan: dict[str, Any]) -> dict[str, Any]:
    previous = load_scan(workspace)
    normalized = normalize_scan_record(workspace, scan)
    normalized["schema"] = SCAN_SCHEMA
    normalized["version"] = coerce_int((previous or {}).get("version"), 0) + 1
    write_yaml(scan_record_path(workspace), normalized)
    reserve_state_version(workspace)
    save_metadata(workspace)
    return normalized


def load_scan(workspace: Workspace) -> dict[str, Any] | None:
    path = scan_record_path(workspace)
    if not path.exists():
        return None
    return normalize_scan_record(workspace, read_yaml(path))


def latest_scan(workspace: Workspace) -> dict[str, Any] | None:
    return load_scan(workspace)


def doc_record_path(workspace: Workspace, doc_path: str) -> Path:
    return workspace.config.storage_dir / "docs" / doc_record_filename(doc_path)


def load_doc_record(workspace: Workspace, doc_path: str) -> dict[str, Any] | None:
    path = doc_record_path(workspace, doc_path)
    return normalize_doc_record(workspace, read_yaml(path)) if path.exists() else None


def save_doc_record(workspace: Workspace, record: dict[str, Any]) -> None:
    normalized = normalize_doc_record(workspace, record)
    normalized["schema"] = DOC_RECORD_SCHEMA
    normalized["version"] = reserve_state_version(workspace)
    write_yaml(doc_record_path(workspace, str(normalized["doc_path"])), normalized)
    save_metadata(workspace)


def iter_doc_records(workspace: Workspace) -> list[dict[str, Any]]:
    docs_dir = workspace.config.storage_dir / "docs"
    if not docs_dir.exists():
        return []
    records = (normalize_doc_record(workspace, read_yaml(path)) for path in docs_dir.glob("*.yaml"))
    return sorted(records, key=lambda record: str(record.get("doc_path", "")))


def migrate_workspace_state(workspace: Workspace) -> None:
    storage_dir = workspace.config.storage_dir
    scan_path = scan_record_path(workspace)
    docs_dir = storage_dir / "docs"

    metadata = strip_timestamp_keys(dict(workspace.metadata))
    metadata_changed = metadata != workspace.metadata
    if coerce_int(metadata.get("schema_version"), 0) != STORAGE_SCHEMA_VERSION:
        metadata["schema_version"] = STORAGE_SCHEMA_VERSION
        metadata_changed = True

    for removed_key in ("next_scan_number", "last_scan_id"):
        if removed_key in metadata:
            metadata.pop(removed_key, None)
            metadata_changed = True

    base_state_version = coerce_int(metadata.get("state_version"), 0)
    if base_state_version <= 0:
        metadata["state_version"] = 1
        metadata_changed = True
        base_state_version = 1

    if scan_path.exists():
        migrated_scan = normalize_scan_record(workspace, read_yaml(scan_path))
        if migrated_scan != read_yaml(scan_path):
            write_yaml(scan_path, migrated_scan)

    doc_versions: list[int] = []
    if docs_dir.exists():
        for path in sorted(docs_dir.glob("*.yaml")):
            migrated = normalize_doc_record(workspace, read_yaml(path))
            version = coerce_int(migrated.get("version"), 0)
            if version <= 0:
                version = base_state_version
                migrated["version"] = version
            doc_versions.append(version)
            write_yaml(path, migrated)

    migrated_state_version = max([base_state_version, *doc_versions, 1])
    if coerce_int(metadata.get("state_version"), 0) != migrated_state_version:
        metadata["state_version"] = migrated_state_version
        metadata_changed = True

    workspace.metadata = metadata
    if metadata_changed:
        write_yaml(storage_dir / "storage.yaml", metadata)
