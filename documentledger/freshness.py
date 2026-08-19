"""Shared freshness preparation and application for canonical and legacy commands."""

from __future__ import annotations

import copy
import json
from typing import Any

from documentledger.doc_index import doc_sections_for_file
from documentledger.errors import DocumentledgerError
from documentledger.identity import normalize_repo_path
from documentledger.impact import resolve_affected_sections
from documentledger.links import current_source_inventory
from documentledger.scanner import collect_files, file_hash
from documentledger.storage import latest_scan, load_doc_record, save_doc_records_batch


def _new_doc_record(workspace: Any, doc_path: str) -> dict[str, Any]:
    return {
        "schema": "documentledger.doc_record.v4",
        "doc_path": doc_path,
        "linked_sources": [],
        "sections": [section.to_record() | {"links": []} for section in doc_sections_for_file(workspace.config.root / doc_path, doc_path)],
        "last_fresh_scan_version": 0,
        "last_fresh_hash": "",
        "notes": "",
        "version": 0,
    }


def _record_for_doc(workspace: Any, doc_path: str) -> dict[str, Any]:
    path = workspace.config.root / doc_path
    if not path.exists() or not path.is_file():
        raise DocumentledgerError("document_not_found", f"Configured document does not exist: {doc_path}")
    return load_doc_record(workspace, doc_path) or _new_doc_record(workspace, doc_path)


def _selected_sections_for_doc(
    workspace: Any,
    doc_path: str,
    record: dict[str, Any],
    section_ref: str | None,
    *,
    all_docs: bool,
    affected: bool,
    allow_unlinked: bool,
) -> list[dict[str, Any]]:
    if not (record.get("linked_sources", []) or []) and not allow_unlinked:
        raise DocumentledgerError(
            "unlinked_doc",
            f"{doc_path} has no linked sources; mark-fresh is rejected for unlinked docs by default.",
            [
                "Add links with `documentledger link add` or `documentledger link add-section` before marking this doc fresh.",
                "Pass --allow-unlinked to record this doc as intentionally unlinked.",
            ],
        )
    sections = list(record.get("sections", []) or [])
    if section_ref:
        wanted = [section for section in sections if section_ref in {str(section.get("heading_slug")), str(section.get("section_id"))}]
        if not wanted:
            raise DocumentledgerError("section_not_found", f"No section {section_ref} exists in {doc_path}")
        return wanted
    if all_docs:
        return sections
    affected_ids = {str(item["section_id"]) for item in resolve_affected_sections(workspace, docs=[doc_path])}
    if affected:
        return [section for section in sections if str(section.get("section_id")) in affected_ids]
    return [section for section in sections if str(section.get("section_id")) in affected_ids] or sections


def _refresh_record(
    workspace: Any,
    record: dict[str, Any],
    sections: list[dict[str, Any]],
    inventory: dict[str, dict[str, Any]],
    scan_version: int,
    reason: str,
) -> tuple[dict[str, Any], list[str]]:
    refreshed = copy.deepcopy(record)
    current_sections = {
        section.section_id: section
        for section in doc_sections_for_file(workspace.config.root / str(record["doc_path"]), str(record["doc_path"]))
    }
    updated_sections: list[str] = []
    refreshed_sections = {str(section.get("section_id")): section for section in refreshed.get("sections", []) or []}
    for selected in sections:
        section_id = str(selected.get("section_id"))
        selected = refreshed_sections.get(section_id, selected)
        current_section = current_sections.get(section_id)
        if current_section is not None:
            selected["heading_path"] = list(current_section.heading_path)
            selected["heading_slug"] = current_section.heading_slug
            selected["line_span"] = [current_section.line_span[0], current_section.line_span[1]]
            selected["section_hash"] = current_section.section_hash
            selected["summary"] = current_section.summary
        for link in selected.get("links", []) or []:
            source_id = str(link.get("source_id", ""))
            if source_id not in inventory:
                raise DocumentledgerError("source_unit_not_found", f"Cannot mark fresh while linked source unit is missing: {source_id}")
            current_unit = inventory[source_id]
            tracked = dict(link.get("tracked_hashes", {}))
            link["tracked_hashes"] = {name: str(current_unit["hashes"][name]) for name in tracked if name in current_unit.get("hashes", {})}
        updated_sections.append(f"{record['doc_path']}::{selected.get('heading_slug', section_id)}")
    refreshed["last_fresh_scan_version"] = scan_version
    refreshed["last_fresh_hash"] = file_hash(workspace.config.root / str(record["doc_path"]))
    refreshed["notes"] = reason if refreshed.get("linked_sources") else f"{reason} (intentionally unlinked)"
    return refreshed, updated_sections


def mark_fresh(
    workspace: Any,
    *,
    doc: str | None = None,
    section: str | None = None,
    all_docs: bool = False,
    affected: bool = False,
    allow_unlinked: bool = False,
    reason: str,
) -> dict[str, Any]:
    """Preflight and atomically apply freshness updates for one selector."""
    if not reason.strip():
        raise DocumentledgerError("reason_required", "mark-fresh requires a non-empty reason.")
    if sum(bool(value) for value in (doc, all_docs, affected)) > 1:
        raise DocumentledgerError("invalid_selector", "Use exactly one of --doc, --all, or --affected.")
    if section and not doc:
        raise DocumentledgerError("doc_required", "Use --doc when selecting --section.")
    scan_record = latest_scan(workspace)
    if scan_record is None:
        raise DocumentledgerError("scan_missing", "mark-fresh requires a latest scan.")

    if doc:
        doc_paths = [normalize_repo_path(doc)]
        mode = "doc"
    elif all_docs:
        doc_paths = collect_files(workspace, workspace.config.doc_roots, workspace.config.doc_extensions)
        mode = "all"
    elif affected:
        doc_paths = sorted({str(item["doc_path"]) for item in resolve_affected_sections(workspace)})
        mode = "affected"
    else:
        raise DocumentledgerError("doc_required", "Select --doc DOC, --all, or --affected.")

    inventory = current_source_inventory(workspace)
    changed_records: list[dict[str, Any]] = []
    updated_sections: list[str] = []
    skipped_docs: list[str] = []

    # Complete preflight: no records are written until every selected document
    # and every linked source unit has been checked and prepared successfully.
    for doc_path in doc_paths:
        record = _record_for_doc(workspace, doc_path)
        selected_sections = _selected_sections_for_doc(
            workspace,
            doc_path,
            record,
            section,
            all_docs=all_docs,
            affected=affected,
            allow_unlinked=allow_unlinked,
        )
        refreshed, section_ids = _refresh_record(workspace, record, selected_sections, inventory, int(scan_record["version"]), reason)
        updated_sections.extend(section_ids)
        if json.dumps(record, sort_keys=True) != json.dumps(refreshed, sort_keys=True):
            changed_records.append(refreshed)
        else:
            skipped_docs.append(doc_path)

    if changed_records:
        save_doc_records_batch(workspace, changed_records)

    return {
        "selected_docs": doc_paths,
        "selected_sections": updated_sections,
        "skipped_docs": skipped_docs,
        "updated_docs": doc_paths,
        "updated_sections": updated_sections,
        "scan_version": int(scan_record["version"]),
        "selector": mode,
    }
