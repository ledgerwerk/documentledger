from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, overload

from ledgercore.errors import LedgerCoreError, YamlStoreError
from ledgercore.hashing import sha256_text
from ledgercore.jsonio import JsonStoreError, canonical_json, load_json_object
from ledgercore.jsonio import write_json as core_write_json
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

CONFIG_NAMES = ("documentledger.toml", ".documentledger.toml")
STORAGE_SCHEMA_VERSION = 5
SCAN_SCHEMA = "documentledger.scan.v5"
SOURCE_INDEX_SCHEMA = "documentledger.source_index.v1"
DOC_RECORD_SCHEMA = "documentledger.doc_record.v4"
SCAN_FILENAME = "scan.yaml"
SOURCE_INDEX_FILENAME = "source-index.json"
TIMESTAMP_KEYS = {f"{prefix}_at" for prefix in ("created", "updated", "generated")}
_UNSET: object = object()
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


def read_json(path: Path) -> dict[str, Any]:
    try:
        return dict(load_json_object(path, label=str(path)))
    except JsonStoreError as exc:
        raise DocumentledgerError("invalid_json", f"Invalid JSON in {path}: {exc}") from exc


def write_json(path: Path, data: dict[str, Any], *, compact: bool = False) -> None:
    try:
        core_write_json(path, data, sort_keys=True, indent=None if compact else 2, compact=compact)
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


def default_metadata(project_uuid: str) -> dict[str, Any]:
    return {
        "schema_version": STORAGE_SCHEMA_VERSION,
        "project_uuid": project_uuid,
        "state_version": 1,
        "last_scan_version": 0,
        "last_scan_source_file_count": 0,
        "last_scan_source_unit_count": 0,
        "last_scan_doc_file_count": 0,
        "last_scan_changed_source_count": 0,
        "last_scan_affected_section_count": 0,
        "last_scan_stale_doc_count": 0,
        "last_scan_unlinked_changed_source_count": 0,
        "last_scan_source_index_file": SOURCE_INDEX_FILENAME,
        "last_scan_source_index_hash": "",
    }


def validate_storage_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    normalized = strip_timestamp_keys(dict(metadata))
    schema_version = coerce_int(normalized.get("schema_version"), 0)
    if schema_version != STORAGE_SCHEMA_VERSION:
        raise DocumentledgerError(
            "schema_mismatch",
            f"storage.yaml schema_version {schema_version} is incompatible; expected {STORAGE_SCHEMA_VERSION}.",
        )
    state = coerce_int(normalized.get("state_version"), 0)
    if state <= 0:
        raise DocumentledgerError("invalid_storage_state", "storage.yaml must contain a positive state_version.")
    project_uuid = str(normalized.get("project_uuid") or "").strip()
    if not project_uuid:
        raise DocumentledgerError("invalid_storage_state", "storage.yaml is missing project_uuid.")
    normalized["schema_version"] = STORAGE_SCHEMA_VERSION
    normalized["state_version"] = state
    normalized["project_uuid"] = project_uuid
    for key, default in default_metadata(project_uuid).items():
        normalized.setdefault(key, default)
    normalized["last_scan_version"] = coerce_int(normalized.get("last_scan_version"), 0)
    normalized["last_scan_source_file_count"] = coerce_int(normalized.get("last_scan_source_file_count"), 0)
    normalized["last_scan_source_unit_count"] = coerce_int(normalized.get("last_scan_source_unit_count"), 0)
    normalized["last_scan_doc_file_count"] = coerce_int(normalized.get("last_scan_doc_file_count"), 0)
    normalized["last_scan_changed_source_count"] = coerce_int(normalized.get("last_scan_changed_source_count"), 0)
    normalized["last_scan_affected_section_count"] = coerce_int(normalized.get("last_scan_affected_section_count"), 0)
    normalized["last_scan_stale_doc_count"] = coerce_int(normalized.get("last_scan_stale_doc_count"), 0)
    normalized["last_scan_unlinked_changed_source_count"] = coerce_int(normalized.get("last_scan_unlinked_changed_source_count"), 0)
    normalized["last_scan_source_index_file"] = str(normalized.get("last_scan_source_index_file") or SOURCE_INDEX_FILENAME)
    normalized["last_scan_source_index_hash"] = str(normalized.get("last_scan_source_index_hash") or "")
    return normalized


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
        return Workspace(config=config, metadata={})
    metadata = validate_storage_metadata(read_yaml(metadata_path))
    return Workspace(config=config, metadata=metadata)


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
    config_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        config_path.write_text(config_text, encoding="utf-8")
    except OSError as exc:
        raise DocumentledgerError("storage_write_failed", f"Failed to write {config_path}: {exc}") from exc
    config = load_config(config_path)
    metadata = default_metadata(project_uuid)
    for name_dir in ("docs", "rendered"):
        (config.storage_dir / name_dir).mkdir(parents=True, exist_ok=True)
    write_yaml(config.storage_dir / "storage.yaml", metadata)
    return Workspace(config=config, metadata=metadata)


def state_version(workspace: Workspace) -> int:
    return coerce_int(workspace.metadata.get("state_version"), 0)


def next_state_version(workspace: Workspace) -> int:
    return state_version(workspace) + 1


def set_state_version(workspace: Workspace, version: int) -> None:
    workspace.metadata["state_version"] = version


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


def normalize_doc_record(
    workspace: Workspace,
    record: dict[str, Any],
    *,
    indexed_sections: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    normalized = strip_timestamp_keys(dict(record))
    doc_path = normalize_repo_path(str(normalized.get("doc_path", "")))
    indexed = indexed_sections if indexed_sections is not None else doc_sections_map(workspace, doc_path)
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


def normalize_source_index_payload(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    normalized = strip_timestamp_keys(dict(payload))
    if str(normalized.get("schema") or "") != SOURCE_INDEX_SCHEMA:
        raise DocumentledgerError(
            "schema_mismatch",
            f"source index schema {normalized.get('schema')!r} is incompatible; expected {SOURCE_INDEX_SCHEMA}.",
        )
    raw_units = dict(normalized.get("source_units", {}))
    return {
        source_id: normalize_source_unit_record(str(source_id), dict(data), str(data.get("path") or ""))
        for source_id, data in raw_units.items()
    }


def source_index_payload(source_units: dict[str, dict[str, Any]]) -> dict[str, Any]:
    normalized_units = {
        source_id: normalize_source_unit_record(str(source_id), dict(data), str(data.get("path") or ""))
        for source_id, data in source_units.items()
    }
    return {"schema": SOURCE_INDEX_SCHEMA, "source_units": normalized_units}


def normalize_scan_summary(record: dict[str, Any], *, source_unit_count: int | None = None) -> dict[str, Any]:
    normalized = strip_timestamp_keys(dict(record))
    if str(normalized.get("schema") or "") != SCAN_SCHEMA:
        raise DocumentledgerError(
            "schema_mismatch",
            f"scan schema {normalized.get('schema')!r} is incompatible; expected {SCAN_SCHEMA}.",
        )
    source_hashes = {str(key): str(value) for key, value in dict(normalized.get("source_hashes", {})).items()}
    doc_hashes = {str(key): str(value) for key, value in dict(normalized.get("doc_hashes", {})).items()}
    summary_source_units = coerce_int(normalized.get("source_unit_count"), source_unit_count or 0)
    return {
        "schema": SCAN_SCHEMA,
        "version": coerce_int(normalized.get("version"), 0),
        "source_index_file": str(normalized.get("source_index_file") or SOURCE_INDEX_FILENAME),
        "source_index_hash": str(normalized.get("source_index_hash") or ""),
        "source_file_count": coerce_int(normalized.get("source_file_count"), len(source_hashes)),
        "source_unit_count": summary_source_units,
        "doc_file_count": coerce_int(normalized.get("doc_file_count"), len(doc_hashes)),
        "source_hashes": source_hashes,
        "doc_hashes": doc_hashes,
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


def build_scan_summary(scan: dict[str, Any], *, version: int, source_index_hash: str, source_index_file: str) -> dict[str, Any]:
    source_units = {
        source_id: normalize_source_unit_record(str(source_id), dict(data), str(data.get("path") or ""))
        for source_id, data in dict(scan.get("source_units", {})).items()
    }
    return normalize_scan_summary(
        {
            "schema": SCAN_SCHEMA,
            "version": version,
            "source_index_file": source_index_file,
            "source_index_hash": source_index_hash,
            "source_file_count": len(dict(scan.get("source_hashes", {}))),
            "source_unit_count": len(source_units),
            "doc_file_count": len(dict(scan.get("doc_hashes", {}))),
            "source_hashes": dict(scan.get("source_hashes", {})),
            "doc_hashes": dict(scan.get("doc_hashes", {})),
            "changed_sources": list(scan.get("changed_sources", []) or []),
            "deleted_sources": list(scan.get("deleted_sources", []) or []),
            "changed_units": list(scan.get("changed_units", []) or []),
            "added_units": list(scan.get("added_units", []) or []),
            "deleted_units": list(scan.get("deleted_units", []) or []),
            "affected_sections": list(scan.get("affected_sections", []) or []),
            "stale_docs": list(scan.get("stale_docs", []) or []),
            "unlinked_changed_sources": list(scan.get("unlinked_changed_sources", []) or []),
            "unmapped_changed_units": list(scan.get("unmapped_changed_units", []) or []),
        },
        source_unit_count=len(source_units),
    )


def scan_record_path(workspace: Workspace) -> Path:
    return workspace.config.storage_dir / SCAN_FILENAME


def source_index_path(workspace: Workspace, file_name: str | None = None) -> Path:
    return workspace.config.storage_dir / (file_name or SOURCE_INDEX_FILENAME)


def update_scan_metadata(workspace: Workspace, summary: dict[str, Any]) -> None:
    workspace.metadata["last_scan_version"] = coerce_int(summary.get("version"), 0)
    workspace.metadata["last_scan_source_file_count"] = coerce_int(summary.get("source_file_count"), 0)
    workspace.metadata["last_scan_source_unit_count"] = coerce_int(summary.get("source_unit_count"), 0)
    workspace.metadata["last_scan_doc_file_count"] = coerce_int(summary.get("doc_file_count"), 0)
    workspace.metadata["last_scan_changed_source_count"] = len(list(summary.get("changed_sources", []) or []))
    workspace.metadata["last_scan_affected_section_count"] = len(list(summary.get("affected_sections", []) or []))
    workspace.metadata["last_scan_stale_doc_count"] = len(list(summary.get("stale_docs", []) or []))
    workspace.metadata["last_scan_unlinked_changed_source_count"] = len(list(summary.get("unlinked_changed_sources", []) or []))
    workspace.metadata["last_scan_source_index_file"] = str(summary.get("source_index_file") or SOURCE_INDEX_FILENAME)
    workspace.metadata["last_scan_source_index_hash"] = str(summary.get("source_index_hash") or "")


def stage_yaml(path: Path, data: dict[str, Any]) -> Path:
    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        core_write_yaml(temp_path, data, sort_keys=False)
    except LedgerCoreError as exc:
        raise DocumentledgerError("storage_write_failed", f"Failed to write {temp_path}: {exc}") from exc
    return temp_path


def stage_json(path: Path, data: dict[str, Any], *, compact: bool = False) -> Path:
    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        core_write_json(temp_path, data, sort_keys=True, indent=None if compact else 2, compact=compact)
    except LedgerCoreError as exc:
        raise DocumentledgerError("storage_write_failed", f"Failed to write {temp_path}: {exc}") from exc
    return temp_path


def commit_staged_files(staged: list[tuple[Path, Path]]) -> None:
    try:
        for temp_path, final_path in staged:
            final_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path.replace(final_path)
    finally:
        for temp_path, _ in staged:
            if temp_path.exists():
                temp_path.unlink()


def save_scan(workspace: Workspace, scan: dict[str, Any]) -> dict[str, Any]:
    previous = load_scan_summary(workspace)
    version = coerce_int((previous or {}).get("version"), 0) + 1
    source_units = {
        source_id: normalize_source_unit_record(str(source_id), dict(data), str(data.get("path") or ""))
        for source_id, data in dict(scan.get("source_units", {})).items()
    }
    index_payload = source_index_payload(source_units)
    index_hash = sha256_text(canonical_json(index_payload))
    summary = build_scan_summary(scan, version=version, source_index_hash=index_hash, source_index_file=SOURCE_INDEX_FILENAME)
    metadata = dict(workspace.metadata)
    metadata["state_version"] = next_state_version(workspace)
    temp_workspace = Workspace(config=workspace.config, metadata=metadata)
    update_scan_metadata(temp_workspace, summary)
    staged = [
        (stage_json(source_index_path(workspace), index_payload, compact=True), source_index_path(workspace)),
        (stage_yaml(scan_record_path(workspace), summary), scan_record_path(workspace)),
        (stage_yaml(workspace.config.storage_dir / "storage.yaml", temp_workspace.metadata), workspace.config.storage_dir / "storage.yaml"),
    ]
    commit_staged_files(staged[:-1])
    commit_staged_files([staged[-1]])
    workspace.metadata = temp_workspace.metadata
    return summary | {"source_units": source_units}


def load_scan_summary(workspace: Workspace) -> dict[str, Any] | None:
    path = scan_record_path(workspace)
    if not path.exists():
        return None
    return normalize_scan_summary(read_yaml(path))


def load_source_index(workspace: Workspace, summary: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    active_summary = summary or load_scan_summary(workspace)
    if active_summary is None:
        return {}
    payload = read_json(source_index_path(workspace, str(active_summary.get("source_index_file") or SOURCE_INDEX_FILENAME)))
    source_units = normalize_source_index_payload(payload)
    expected_hash = str(active_summary.get("source_index_hash") or "")
    if expected_hash and sha256_text(canonical_json(source_index_payload(source_units))) != expected_hash:
        raise DocumentledgerError("source_index_hash_mismatch", "source-index.json does not match scan.yaml.")
    return source_units


def load_scan(workspace: Workspace) -> dict[str, Any] | None:
    summary = load_scan_summary(workspace)
    if summary is None:
        return None
    return summary | {"source_units": load_source_index(workspace, summary)}


def latest_scan_summary(workspace: Workspace) -> dict[str, Any] | None:
    return load_scan_summary(workspace)


def latest_scan(workspace: Workspace) -> dict[str, Any] | None:
    return load_scan(workspace)


def doc_record_path(workspace: Workspace, doc_path: str) -> Path:
    return workspace.config.storage_dir / "docs" / doc_record_filename(doc_path)


def load_doc_record(
    workspace: Workspace,
    doc_path: str,
    *,
    indexed_sections: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    path = doc_record_path(workspace, doc_path)
    return normalize_doc_record(workspace, read_yaml(path), indexed_sections=indexed_sections) if path.exists() else None


def save_doc_record(workspace: Workspace, record: dict[str, Any]) -> None:
    version = next_state_version(workspace)
    normalized = normalize_doc_record(workspace, record)
    normalized["schema"] = DOC_RECORD_SCHEMA
    normalized["version"] = version
    metadata = dict(workspace.metadata)
    metadata["state_version"] = version
    staged = [
        (
            stage_yaml(doc_record_path(workspace, str(normalized["doc_path"])), normalized),
            doc_record_path(workspace, str(normalized["doc_path"])),
        ),
        (stage_yaml(workspace.config.storage_dir / "storage.yaml", metadata), workspace.config.storage_dir / "storage.yaml"),
    ]
    commit_staged_files(staged[:-1])
    commit_staged_files([staged[-1]])
    workspace.metadata = metadata


def save_doc_records_batch(workspace: Workspace, records: list[dict[str, Any]]) -> int:
    if not records:
        return state_version(workspace)
    version = next_state_version(workspace)
    normalized_records = [normalize_doc_record(workspace, record) for record in records]
    for record in normalized_records:
        record["schema"] = DOC_RECORD_SCHEMA
        record["version"] = version
    metadata = dict(workspace.metadata)
    metadata["state_version"] = version
    staged = [
        *(
            (stage_yaml(doc_record_path(workspace, str(record["doc_path"])), record), doc_record_path(workspace, str(record["doc_path"])))
            for record in normalized_records
        ),
        (stage_yaml(workspace.config.storage_dir / "storage.yaml", metadata), workspace.config.storage_dir / "storage.yaml"),
    ]
    commit_staged_files(staged[:-1])
    commit_staged_files([staged[-1]])
    workspace.metadata = metadata
    return version


def iter_doc_records(workspace: Workspace) -> list[dict[str, Any]]:
    docs_dir = workspace.config.storage_dir / "docs"
    if not docs_dir.exists():
        return []
    records = []
    for path in sorted(docs_dir.glob("*.yaml")):
        records.append(normalize_doc_record(workspace, read_yaml(path)))
    return sorted(records, key=lambda record: str(record.get("doc_path", "")))


@dataclass
class CommandState:
    workspace: Workspace
    scan_summary: dict[str, Any] | None | object = _UNSET
    source_units: dict[str, dict[str, Any]] | object = _UNSET
    doc_records: dict[str, dict[str, Any]] = field(default_factory=dict)
    doc_sections: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)
    _doc_records_loaded: bool = False

    def get_scan_summary(self) -> dict[str, Any] | None:
        if self.scan_summary is _UNSET:
            self.scan_summary = load_scan_summary(self.workspace)
        return self.scan_summary if self.scan_summary is not _UNSET else None

    def get_source_units(self) -> dict[str, dict[str, Any]]:
        if self.source_units is _UNSET:
            summary = self.get_scan_summary()
            self.source_units = load_source_index(self.workspace, summary) if summary else {}
        return self.source_units if self.source_units is not _UNSET else {}

    def get_scan(self) -> dict[str, Any] | None:
        summary = self.get_scan_summary()
        if summary is None:
            return None
        return summary | {"source_units": self.get_source_units()}

    def get_doc_sections(self, doc_path: str) -> dict[str, dict[str, Any]]:
        normalized = normalize_repo_path(doc_path)
        if normalized not in self.doc_sections:
            self.doc_sections[normalized] = doc_sections_map(self.workspace, normalized)
        return self.doc_sections[normalized]

    def get_doc_record(self, doc_path: str) -> dict[str, Any] | None:
        normalized = normalize_repo_path(doc_path)
        if normalized in self.doc_records:
            return self.doc_records[normalized]
        record = load_doc_record(self.workspace, normalized, indexed_sections=self.get_doc_sections(normalized))
        if record is not None:
            self.doc_records[normalized] = record
        return record

    def list_doc_records(self) -> list[dict[str, Any]]:
        if not self._doc_records_loaded:
            docs_dir = self.workspace.config.storage_dir / "docs"
            for path in sorted(docs_dir.glob("*.yaml")) if docs_dir.exists() else []:
                payload = read_yaml(path)
                record = normalize_doc_record(
                    self.workspace,
                    payload,
                    indexed_sections=self.get_doc_sections(str(payload.get("doc_path") or "")),
                )
                self.doc_records[str(record.get("doc_path", ""))] = record
            self._doc_records_loaded = True
        return [self.doc_records[key] for key in sorted(self.doc_records)]
