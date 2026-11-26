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
from documentledger.models import FreshnessResolution
from documentledger.scanner import collect_files, file_hash
from documentledger.storage import DOC_RECORD_SCHEMA, latest_scan, load_doc_record, save_doc_records_batch


def _new_doc_record(workspace: Any, doc_path: str) -> dict[str, Any]:
    return {
        "schema": DOC_RECORD_SCHEMA,
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
        selected.pop("pending_section_hash", None)
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
    if refreshed.get("linked_sources"):
        refreshed["coverage_resolution"] = None
    else:
        refreshed["coverage_resolution"] = {
            "state": "intentionally_unlinked",
            "reason": reason.strip(),
            "scan_version": scan_version,
            "content_hash": refreshed["last_fresh_hash"],
        }
    return refreshed, updated_sections


def record_freshness_resolutions(workspace: Any, resolutions: tuple[FreshnessResolution, ...]) -> None:
    if not resolutions:
        return
    scan_record = latest_scan(workspace)
    if scan_record is None:
        raise DocumentledgerError("scan_missing", "Freshness resolution requires a latest source scan.")

    grouped: dict[str, list[FreshnessResolution]] = {}
    for resolution in resolutions:
        grouped.setdefault(resolution.doc_path, []).append(resolution)

    inventory = current_source_inventory(workspace)
    records: list[dict[str, Any]] = []
    for doc_path, doc_resolutions in sorted(grouped.items()):
        record = load_doc_record(workspace, doc_path)
        if record is None:
            raise DocumentledgerError("doc_record_missing", f"No document record exists for {doc_path}.")
        selected_ids = {item.section_id for item in doc_resolutions}
        selected = [section for section in (record.get("sections", []) or []) if str(section.get("section_id", "")) in selected_ids]
        if {str(section.get("section_id", "")) for section in selected} != selected_ids:
            raise DocumentledgerError("section_not_found", f"A freshness section no longer exists in {doc_path}.")
        reason = "Documentledger finish passed link audit and configured validation."
        refreshed, _ = _refresh_record(workspace, record, selected, inventory, int(scan_record["version"]), reason)
        refreshed_sections = {str(section.get("section_id", "")): section for section in refreshed.get("sections", []) or []}
        for resolution in doc_resolutions:
            section = refreshed_sections[resolution.section_id]
            if resolution.disposition != "updated" and not resolution.reason.strip():
                raise DocumentledgerError("reason_required", f"{resolution.disposition} requires a non-empty reason.")
            section["freshness"] = {
                "source_scan_version": resolution.scan_version,
                "section_hash": str(section.get("section_hash", "")),
                "disposition": resolution.disposition,
                "reason": resolution.reason,
            }
        records.append(refreshed)

    workspace.metadata["last_scan_affected_section_count"] = 0
    workspace.metadata["last_scan_stale_doc_count"] = 0
    save_doc_records_batch(workspace, records)


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
        old_sections = {str(item.get("section_id", "")): item for item in record.get("sections", []) or []}
        selected_ids = {str(item.get("section_id", "")) for item in selected_sections}
        for refreshed_section in refreshed.get("sections", []) or []:
            section_id = str(refreshed_section.get("section_id", ""))
            if section_id not in selected_ids:
                continue
            old_section = old_sections.get(section_id, {})
            previous_freshness = dict(old_section.get("freshness", {}) or {})
            baseline_hash = str(
                old_section.get("pending_section_hash") or previous_freshness.get("section_hash") or old_section.get("section_hash", "")
            )
            section_hash = str(refreshed_section.get("section_hash", ""))
            disposition = "updated" if baseline_hash != section_hash else "reviewed-no-change"
            refreshed_section["freshness"] = {
                "source_scan_version": int(scan_record["version"]),
                "section_hash": section_hash,
                "disposition": disposition,
                "reason": reason,
            }
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
