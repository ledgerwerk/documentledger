from __future__ import annotations

from pathlib import Path

from documentledger.errors import DocumentledgerError
from documentledger.identity import normalize_repo_path
from documentledger.models import Workspace
from documentledger.storage import (
    iter_doc_records,
    load_doc_record,
    now_iso,
    save_doc_record,
)


def ensure_extension(path: str, extensions: list[str], kind: str) -> None:
    if Path(path).suffix not in extensions:
        raise DocumentledgerError("invalid_extension", f"{kind} path has an unsupported extension: {path}")


def validate_existing(workspace: Workspace, path: str, extensions: list[str], kind: str) -> str:
    normalized = normalize_repo_path(path)
    ensure_extension(normalized, extensions, kind)
    if not (workspace.config.root / normalized).exists():
        raise DocumentledgerError(f"missing_{kind}", f"{kind.capitalize()} path does not exist: {normalized}")
    return normalized


def add_link(workspace: Workspace, doc: str, source: str, reason: str | None = None) -> dict[str, object]:
    doc_path = validate_existing(workspace, doc, workspace.config.doc_extensions, "doc")
    source_path = validate_existing(workspace, source, workspace.config.source_extensions, "source")
    record = load_doc_record(workspace, doc_path) or {
        "schema": "documentledger.doc_record.v1",
        "doc_path": doc_path,
        "linked_sources": [],
        "last_fresh_scan_id": "",
        "last_fresh_hash": "",
        "updated_at": now_iso(),
        "notes": "",
    }
    linked = sorted({*[str(item) for item in record.get("linked_sources", [])], source_path})
    record["linked_sources"] = linked
    record["updated_at"] = now_iso()
    if reason:
        record["notes"] = reason
    save_doc_record(workspace, record)
    return record


def remove_link(workspace: Workspace, doc: str, source: str) -> dict[str, object]:
    doc_path = normalize_repo_path(doc)
    source_path = normalize_repo_path(source)
    record = load_doc_record(workspace, doc_path)
    if record is None:
        raise DocumentledgerError("doc_record_missing", f"No doc record exists for {doc_path}")
    record["linked_sources"] = sorted(item for item in record.get("linked_sources", []) if item != source_path)
    record["updated_at"] = now_iso()
    save_doc_record(workspace, record)
    return record


def list_links(workspace: Workspace) -> list[dict[str, object]]:
    return iter_doc_records(workspace)


def docs_for_source(workspace: Workspace, source: str) -> list[str]:
    return sorted(str(record["doc_path"]) for record in iter_doc_records(workspace) if source in (record.get("linked_sources", []) or []))
