from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from documentledger.models import ScanResult, Workspace
from documentledger.storage import (
    iter_doc_records,
    latest_scan,
    next_scan_id,
    now_iso,
    save_scan,
)

EXCLUDED_NAMES = {".git", ".cache", "__pycache__", "build", "dist", ".tox", ".nox", ".venv", "venv", "env"}


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def collect_files(workspace: Workspace, roots: list[str], extensions: list[str]) -> list[str]:
    result: list[str] = []
    storage_dir = workspace.config.storage_dir.resolve()
    for root_text in roots:
        root = workspace.config.root / root_text
        if not root.exists():
            continue
        candidates = [root] if root.is_file() else [p for p in root.rglob("*") if p.is_file()]
        for path in candidates:
            resolved = path.resolve()
            if storage_dir == resolved or storage_dir in resolved.parents:
                continue
            if any(part in EXCLUDED_NAMES for part in path.relative_to(workspace.config.root).parts):
                continue
            if path.suffix not in extensions:
                continue
            result.append(path.relative_to(workspace.config.root).as_posix())
    return sorted(set(result))


def hash_paths(workspace: Workspace, paths: list[str]) -> dict[str, str]:
    return {path: file_hash(workspace.config.root / path) for path in paths}


def changed_source_paths(previous: dict[str, Any] | None, current_hashes: dict[str, str]) -> tuple[list[str], list[str]]:
    if previous is None:
        return [], []
    old_hashes = dict(previous.get("source_hashes", {}))
    changed = sorted(path for path, value in current_hashes.items() if old_hashes.get(path) != value)
    deleted = sorted(path for path in old_hashes if path not in current_hashes)
    return changed, deleted


def linked_source_map(workspace: Workspace) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = {}
    for record in iter_doc_records(workspace):
        doc_path = str(record.get("doc_path", ""))
        for source in record.get("linked_sources", []) or []:
            mapping.setdefault(str(source), []).append(doc_path)
    return {source: sorted(docs) for source, docs in mapping.items()}


def run_scan(workspace: Workspace) -> ScanResult:
    source_paths = collect_files(workspace, workspace.config.source_roots, workspace.config.source_extensions)
    doc_paths = collect_files(workspace, workspace.config.doc_roots, workspace.config.doc_extensions)
    source_hashes = hash_paths(workspace, source_paths)
    doc_hashes = hash_paths(workspace, doc_paths)
    previous = latest_scan(workspace)
    changed, deleted = changed_source_paths(previous, source_hashes)
    mapping = linked_source_map(workspace)
    stale = sorted({doc for source in [*changed, *deleted] for doc in mapping.get(source, [])})
    unlinked = sorted(source for source in changed if source not in mapping)
    if previous is None:
        changed = []
        deleted = []
        stale = []
        unlinked = []
    scan_id = next_scan_id(workspace)
    scan = {
        "schema": "documentledger.scan.v1",
        "scan_id": scan_id,
        "created_at": now_iso(),
        "source_hashes": source_hashes,
        "doc_hashes": doc_hashes,
        "changed_sources": changed,
        "deleted_sources": deleted,
        "stale_docs": stale,
        "unlinked_changed_sources": unlinked,
    }
    save_scan(workspace, scan)
    return ScanResult(
        scan_id=scan_id,
        changed_sources=changed,
        deleted_sources=deleted,
        stale_docs=stale,
        unlinked_changed_sources=unlinked,
        source_hashes=source_hashes,
        doc_hashes=doc_hashes,
    )
