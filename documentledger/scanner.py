from __future__ import annotations

from pathlib import Path
from typing import Any

from ledgercore.hashing import sha256_bytes

from documentledger.impact import linked_source_map, resolve_affected_sections, unmapped_changed_units
from documentledger.models import ScanResult, Workspace
from documentledger.source_index import source_inventory, source_inventory_for_paths
from documentledger.storage import latest_scan, latest_scan_summary, save_scan

EXCLUDED_NAMES = {".git", ".cache", "__pycache__", "build", "dist", ".tox", ".nox", ".venv", "venv", "env"}


def file_hash(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


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


def changed_source_paths(previous: dict[str, Any] | None, current_hashes: dict[str, str]) -> tuple[list[str], list[str], list[str]]:
    if previous is None:
        return [], [], []
    old_hashes = dict(previous.get("source_hashes", {}))
    changed = sorted(path for path, value in current_hashes.items() if path in old_hashes and old_hashes.get(path) != value)
    added = sorted(path for path in current_hashes if path not in old_hashes)
    deleted = sorted(path for path in old_hashes if path not in current_hashes)
    return changed, added, deleted


def scan_state_changed(previous: dict[str, Any] | None, source_hashes: dict[str, str], doc_hashes: dict[str, str]) -> bool:
    if previous is None:
        return True
    return dict(previous.get("source_hashes", {})) != source_hashes or dict(previous.get("doc_hashes", {})) != doc_hashes


def changed_units(
    previous: dict[str, Any] | None,
    current_units: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    if previous is None:
        return [], [], []
    previous_units = dict(previous.get("source_units", {}))
    changed: list[dict[str, Any]] = []
    added: list[dict[str, Any]] = []
    deleted: list[dict[str, Any]] = []
    for source_id, unit in sorted(current_units.items()):
        old_unit = previous_units.get(source_id)
        if old_unit is None:
            added.append(
                {
                    "source_id": source_id,
                    "path": str(unit.get("path", "")),
                    "kind": str(unit.get("kind", "")),
                    "qualname": str(unit.get("qualname", "")),
                    "change_type": "added",
                    "changed_hashes": sorted(dict(unit.get("hashes", {})).keys()),
                    "old_line_span": [0, 0],
                    "new_line_span": list(unit.get("line_span", [0, 0])),
                }
            )
            continue
        old_hashes = dict(old_unit.get("hashes", {}))
        new_hashes = dict(unit.get("hashes", {}))
        mismatched = sorted(name for name, value in new_hashes.items() if old_hashes.get(name) != value)
        if not mismatched:
            continue
        changed.append(
            {
                "source_id": source_id,
                "path": str(unit.get("path", "")),
                "kind": str(unit.get("kind", "")),
                "qualname": str(unit.get("qualname", "")),
                "change_type": "modified",
                "changed_hashes": mismatched,
                "old_line_span": list(old_unit.get("line_span", [0, 0])),
                "new_line_span": list(unit.get("line_span", [0, 0])),
            }
        )
    for source_id, old_unit in sorted(previous_units.items()):
        if source_id in current_units:
            continue
        deleted.append(
            {
                "source_id": source_id,
                "path": str(old_unit.get("path", "")),
                "kind": str(old_unit.get("kind", "")),
                "qualname": str(old_unit.get("qualname", "")),
                "change_type": "deleted",
                "changed_hashes": sorted(dict(old_unit.get("hashes", {})).keys()),
                "old_line_span": list(old_unit.get("line_span", [0, 0])),
                "new_line_span": [0, 0],
            }
        )
    return filter_unit_changes(changed), filter_unit_changes(added), filter_unit_changes(deleted)


def filter_unit_changes(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_path: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        by_path.setdefault(str(item.get("path", "")), []).append(item)
    filtered: list[dict[str, Any]] = []
    for path_items in by_path.values():
        kinds = {str(item.get("kind", "")) for item in path_items}
        for item in path_items:
            kind = str(item.get("kind", ""))
            if kind == "file" and (kinds - {"file"}):
                continue
            if kind == "module" and (kinds & {"function", "method", "class"}):
                continue
            filtered.append(item)
    return sorted(filtered, key=lambda item: (str(item.get("path", "")), str(item.get("source_id", ""))))


def run_scan(workspace: Workspace) -> ScanResult:
    source_paths = collect_files(workspace, workspace.config.source_roots, workspace.config.source_extensions)
    doc_paths = collect_files(workspace, workspace.config.doc_roots, workspace.config.doc_extensions)
    source_hashes = hash_paths(workspace, source_paths)
    doc_hashes = hash_paths(workspace, doc_paths)
    previous_summary = latest_scan_summary(workspace)
    if not scan_state_changed(previous_summary, source_hashes, doc_hashes):
        assert previous_summary is not None
        return ScanResult(
            version=int(str(previous_summary.get("version", 0))),
            changed_sources=[],
            deleted_sources=[],
            stale_docs=[],
            unlinked_changed_sources=[],
            changed_units=[],
            added_units=[],
            deleted_units=[],
            affected_sections=[],
            unmapped_changed_units=[],
            source_units={},
            source_hashes=source_hashes,
            doc_hashes=doc_hashes,
            unchanged=True,
        )

    previous = latest_scan(workspace) if previous_summary is not None else None
    changed, added, deleted = changed_source_paths(previous_summary, source_hashes)
    source_units: dict[str, dict[str, Any]]
    if previous is None:
        source_units = source_inventory(workspace.config.root, source_paths)
    elif changed or added or deleted:
        previous_units = dict(previous.get("source_units", {}))
        replaced_paths = set(changed) | set(added)
        source_units = {
            source_id: dict(unit)
            for source_id, unit in previous_units.items()
            if str(unit.get("path", "")) not in set(deleted) | replaced_paths
        }
        indexed_paths = sorted(replaced_paths)
        if indexed_paths:
            for unit in source_inventory_for_paths(workspace.config.root, indexed_paths).values():
                source_units[str(unit["source_id"])] = unit
    else:
        source_units = dict(previous.get("source_units", {})) if previous is not None else {}

    changed_unit_records, added_unit_records, deleted_unit_records = changed_units(previous, source_units)
    mapping = linked_source_map(workspace)
    unlinked = sorted(source for source in [*changed, *added] if source not in mapping)
    if previous is None:
        changed = []
        added = []
        deleted = []
        unlinked = []
        changed_unit_records = []
        added_unit_records = []
        deleted_unit_records = []
    scan = {
        "schema": "documentledger.scan.v5",
        "source_hashes": source_hashes,
        "doc_hashes": doc_hashes,
        "source_units": source_units,
        "changed_sources": sorted([*changed, *added]),
        "deleted_sources": deleted,
        "changed_units": changed_unit_records,
        "added_units": added_unit_records,
        "deleted_units": deleted_unit_records,
        "affected_sections": [],
        "stale_docs": [],
        "unlinked_changed_sources": unlinked,
        "unmapped_changed_units": [],
    }
    affected_sections = resolve_affected_sections(workspace, scan=scan)
    scan["affected_sections"] = affected_sections
    scan["stale_docs"] = sorted({str(item["doc_path"]) for item in affected_sections})
    scan["unmapped_changed_units"] = unmapped_changed_units(workspace, scan=scan)
    saved = save_scan(workspace, scan)
    return ScanResult(
        version=int(str(saved.get("version", 0))),
        changed_sources=sorted([*changed, *added]),
        deleted_sources=deleted,
        stale_docs=list(saved["stale_docs"]),
        unlinked_changed_sources=unlinked,
        changed_units=changed_unit_records,
        added_units=added_unit_records,
        deleted_units=deleted_unit_records,
        affected_sections=list(saved["affected_sections"]),
        unmapped_changed_units=list(saved["unmapped_changed_units"]),
        source_units=source_units,
        source_hashes=source_hashes,
        doc_hashes=doc_hashes,
        unchanged=False,
    )
