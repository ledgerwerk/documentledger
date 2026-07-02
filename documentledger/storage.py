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

from documentledger.errors import DocumentledgerError
from documentledger.identity import doc_record_filename, format_scan_id
from documentledger.models import Config, Workspace

CONFIG_NAMES = ("documentledger.toml", ".documentledger.toml")
SCAN_SCHEMA = "documentledger.scan.v2"
DOC_RECORD_SCHEMA = "documentledger.doc_record.v2"
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


def scan_sort_key(path: Path) -> tuple[int, str]:
    suffix = path.stem.rsplit("-", 1)[-1]
    return (coerce_int(suffix, 0), path.stem)


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
        "schema_version": 2,
        "project_uuid": project_uuid,
        "state_version": 1,
        "next_scan_number": 1,
        "last_scan_id": "",
    }
    for name_dir in ("scans", "docs", "rendered"):
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


def next_scan_id(workspace: Workspace) -> str:
    return format_scan_id(coerce_int(workspace.metadata.get("next_scan_number"), 1))


def save_scan(workspace: Workspace, scan: dict[str, Any]) -> None:
    scan["version"] = reserve_state_version(workspace)
    write_yaml(workspace.config.storage_dir / "scans" / f"{scan['scan_id']}.yaml", scan)
    workspace.metadata["next_scan_number"] = coerce_int(workspace.metadata.get("next_scan_number"), 1) + 1
    workspace.metadata["last_scan_id"] = scan["scan_id"]
    save_metadata(workspace)


def load_scan(workspace: Workspace, scan_id: str) -> dict[str, Any]:
    return read_yaml(workspace.config.storage_dir / "scans" / f"{scan_id}.yaml")


def latest_scan(workspace: Workspace) -> dict[str, Any] | None:
    scan_id = str(workspace.metadata.get("last_scan_id") or "")
    return load_scan(workspace, scan_id) if scan_id else None


def doc_record_path(workspace: Workspace, doc_path: str) -> Path:
    return workspace.config.storage_dir / "docs" / doc_record_filename(doc_path)


def load_doc_record(workspace: Workspace, doc_path: str) -> dict[str, Any] | None:
    path = doc_record_path(workspace, doc_path)
    return read_yaml(path) if path.exists() else None


def save_doc_record(workspace: Workspace, record: dict[str, Any]) -> None:
    record["version"] = reserve_state_version(workspace)
    write_yaml(doc_record_path(workspace, str(record["doc_path"])), record)
    save_metadata(workspace)


def iter_doc_records(workspace: Workspace) -> list[dict[str, Any]]:
    docs_dir = workspace.config.storage_dir / "docs"
    if not docs_dir.exists():
        return []
    return sorted((read_yaml(path) for path in docs_dir.glob("*.yaml")), key=lambda r: str(r.get("doc_path", "")))


def migrate_workspace_state(workspace: Workspace) -> None:
    storage_dir = workspace.config.storage_dir
    scan_dir = storage_dir / "scans"
    docs_dir = storage_dir / "docs"

    metadata = strip_timestamp_keys(dict(workspace.metadata))
    metadata_changed = metadata != workspace.metadata

    if metadata.get("schema_version") != 2:
        metadata["schema_version"] = 2
        metadata_changed = True

    next_scan_number = max(1, coerce_int(metadata.get("next_scan_number"), 1))
    if metadata.get("next_scan_number") != next_scan_number:
        metadata["next_scan_number"] = next_scan_number
        metadata_changed = True

    last_scan_id = str(metadata.get("last_scan_id") or "")
    if metadata.get("last_scan_id") != last_scan_id:
        metadata["last_scan_id"] = last_scan_id
        metadata_changed = True

    scan_versions: list[int] = []
    if scan_dir.exists():
        for path in sorted(scan_dir.glob("*.yaml"), key=scan_sort_key):
            record = read_yaml(path)
            migrated = strip_timestamp_keys(dict(record))
            changed = migrated != record
            if migrated.get("schema") != SCAN_SCHEMA:
                migrated["schema"] = SCAN_SCHEMA
                changed = True
            version = coerce_int(migrated.get("version"), 0)
            if version <= 0:
                version = max(1, coerce_int(path.stem.rsplit("-", 1)[-1], 0))
                migrated["version"] = version
                changed = True
            scan_versions.append(version)
            if changed:
                write_yaml(path, migrated)

    base_state_version = coerce_int(metadata.get("state_version"), 0)
    if base_state_version <= 0:
        base_state_version = max([1, next_scan_number - 1, *scan_versions])
        metadata["state_version"] = base_state_version
        metadata_changed = True

    doc_versions: list[int] = []
    if docs_dir.exists():
        for path in sorted(docs_dir.glob("*.yaml")):
            record = read_yaml(path)
            migrated = strip_timestamp_keys(dict(record))
            changed = migrated != record
            if migrated.get("schema") != DOC_RECORD_SCHEMA:
                migrated["schema"] = DOC_RECORD_SCHEMA
                changed = True
            version = coerce_int(migrated.get("version"), 0)
            if version <= 0:
                version = base_state_version
                migrated["version"] = version
                changed = True
            doc_versions.append(version)
            if changed:
                write_yaml(path, migrated)

    migrated_state_version = max([base_state_version, *scan_versions, *doc_versions, 1])
    if coerce_int(metadata.get("state_version"), 0) != migrated_state_version:
        metadata["state_version"] = migrated_state_version
        metadata_changed = True

    workspace.metadata = metadata
    if metadata_changed:
        write_yaml(storage_dir / "storage.yaml", metadata)
