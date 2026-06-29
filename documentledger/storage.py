from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, overload

import yaml

try:
    import tomllib  # type: ignore[import-not-found]
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[import-not-found,no-redef]

from documentledger.errors import DocumentledgerError
from documentledger.identity import doc_record_filename, format_scan_id
from documentledger.models import Config, Workspace

CONFIG_NAMES = ("documentledger.toml", ".documentledger.toml")
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


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_yaml(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as exc:
        raise DocumentledgerError("unreadable_yaml", f"Unreadable YAML: {path}") from exc
    if not isinstance(data, dict):
        raise DocumentledgerError("invalid_yaml", f"Expected mapping in {path}")
    return data


def write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def discover_config(start: Path | None = None) -> Path | None:
    current = (start or Path.cwd()).resolve()
    if current.is_file():
        current = current.parent
    for directory in (current, *current.parents):
        for name in CONFIG_NAMES:
            candidate = directory / name
            if candidate.exists():
                return candidate
    return None


def load_config(path: Path) -> Config:
    data = tomllib.loads(path.read_text())
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
        metadata = {}
    else:
        metadata = read_yaml(metadata_path)
    return Workspace(config=config, metadata=metadata)


def init_workspace(project_name: str | None, documentledger_dir: str, hidden_config: bool) -> Workspace:
    root = Path.cwd().resolve()
    config_path = root / (".documentledger.toml" if hidden_config else "documentledger.toml")
    if any((root / name).exists() for name in CONFIG_NAMES):
        raise DocumentledgerError("already_initialized", "Documentledger is already initialized.")
    project_uuid = str(uuid.uuid4())
    name = project_name or root.name
    config_path.write_text(
        '[ledger]\ncode = "dl"\nname = "documentledger"\n\n'
        f'[project]\nname = "{name}"\nuuid = "{project_uuid}"\n\n'
        f'[storage]\ndocumentledger_dir = "{documentledger_dir}"\n\n'
        '[scan]\nsource_roots = ["documentledger", "tests"]\n'
        'doc_roots = ["docs", "README.md"]\nsource_extensions = [".py"]\n'
        'doc_extensions = [".md", ".rst"]\n\n[validation]\ncommands = []\n\n'
        "[policy]\nrequire_doc_frontmatter = false\n",
        encoding="utf-8",
    )
    config = load_config(config_path)
    created = now_iso()
    metadata = {
        "schema_version": 1,
        "project_uuid": project_uuid,
        "next_scan_number": 1,
        "last_scan_id": "",
        "created_at": created,
        "updated_at": created,
    }
    for name_dir in ("scans", "docs", "rendered"):
        (config.storage_dir / name_dir).mkdir(parents=True, exist_ok=True)
    write_yaml(config.storage_dir / "storage.yaml", metadata)
    return Workspace(config=config, metadata=metadata)


def save_metadata(workspace: Workspace) -> None:
    workspace.metadata["updated_at"] = now_iso()
    write_yaml(workspace.config.storage_dir / "storage.yaml", workspace.metadata)


def next_scan_id(workspace: Workspace) -> str:
    return format_scan_id(int(str(workspace.metadata.get("next_scan_number", 1))))


def save_scan(workspace: Workspace, scan: dict[str, Any]) -> None:
    write_yaml(workspace.config.storage_dir / "scans" / f"{scan['scan_id']}.yaml", scan)
    next_number = int(str(workspace.metadata.get("next_scan_number", 1))) + 1
    workspace.metadata["next_scan_number"] = next_number
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
    write_yaml(doc_record_path(workspace, str(record["doc_path"])), record)


def iter_doc_records(workspace: Workspace) -> list[dict[str, Any]]:
    docs_dir = workspace.config.storage_dir / "docs"
    if not docs_dir.exists():
        return []
    return sorted((read_yaml(path) for path in docs_dir.glob("*.yaml")), key=lambda r: str(r.get("doc_path", "")))
