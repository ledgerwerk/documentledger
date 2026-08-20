"""Durable document-record reconciliation against the live Markdown index."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from documentledger.doc_index import doc_sections_for_file, whole_doc_section
from documentledger.models import Workspace
from documentledger.storage import iter_doc_records, load_doc_record, save_doc_records_batch

SECTION_METADATA_KEYS = (
    "section_id",
    "doc_path",
    "heading_path",
    "heading_slug",
    "line_span",
    "section_hash",
    "summary",
)


@dataclass(frozen=True)
class ReconciliationReport:
    doc_path: str
    changed: bool
    sections_added: tuple[str, ...] = ()
    sections_refreshed: tuple[str, ...] = ()
    unlinked_sections_pruned: tuple[str, ...] = ()
    linked_orphans: tuple[str, ...] = ()


@dataclass
class ReconciliationSummary:
    documents_changed: int = 0
    sections_added: int = 0
    sections_refreshed: int = 0
    unlinked_sections_pruned: int = 0
    linked_orphans: int = 0
    reports: list[ReconciliationReport] = field(default_factory=list)

    def to_record(self) -> dict[str, int]:
        return {
            "documents_changed": self.documents_changed,
            "sections_added": self.sections_added,
            "sections_refreshed": self.sections_refreshed,
            "unlinked_sections_pruned": self.unlinked_sections_pruned,
            "linked_orphans": self.linked_orphans,
        }


def _metadata(record: dict[str, Any]) -> dict[str, Any]:
    return {key: deepcopy(record.get(key)) for key in SECTION_METADATA_KEYS}


def _linked_sources(record: dict[str, Any]) -> list[str]:
    return sorted(
        {
            str(link.get("source_path", ""))
            for section in (record.get("sections", []) or [])
            for link in (section.get("links", []) or [])
            if str(link.get("source_path", ""))
        }
    )


def reconcile_doc_record(
    workspace: Workspace,
    record: dict[str, Any],
) -> tuple[dict[str, Any], ReconciliationReport]:
    """Merge live section inventory with durable links and freshness metadata."""
    doc_path = str(record["doc_path"])
    stored_sections = list(record.get("sections", []) or [])
    if any(str(section.get("section_id", "")).endswith("::whole-doc") for section in stored_sections):
        current_sections = [
            whole_doc_section(
                doc_path,
                (workspace.config.root / doc_path).read_text(encoding="utf-8"),
            ).to_record()
        ]
    else:
        current_sections = [section.to_record() for section in doc_sections_for_file(workspace.config.root / doc_path, doc_path)]
    current_by_id = {str(section["section_id"]): section for section in current_sections}
    stored_by_id = {str(section.get("section_id")): section for section in stored_sections if str(section.get("section_id", ""))}
    reconciled: list[dict[str, Any]] = []
    added: list[str] = []
    refreshed: list[str] = []
    pruned: list[str] = []
    orphans: list[str] = []

    for current in current_sections:
        section_id = str(current["section_id"])
        stored = stored_by_id.get(section_id)
        if stored is None:
            new_section = deepcopy(current)
            new_section["links"] = []
            reconciled.append(new_section)
            added.append(section_id)
            continue
        merged = deepcopy(current)
        merged["links"] = deepcopy(list(stored.get("links", []) or []))
        reconciled.append(merged)
        if _metadata(stored) != _metadata(merged):
            refreshed.append(section_id)

    for section_id in sorted(set(stored_by_id) - set(current_by_id)):
        stored = stored_by_id[section_id]
        if stored.get("links", []) or []:
            reconciled.append(deepcopy(stored))
            orphans.append(section_id)
        else:
            pruned.append(section_id)

    updated = deepcopy(record)
    updated["sections"] = reconciled
    updated["linked_sources"] = _linked_sources(updated)
    changed = updated != record
    return updated, ReconciliationReport(
        doc_path=doc_path,
        changed=changed,
        sections_added=tuple(added),
        sections_refreshed=tuple(refreshed),
        unlinked_sections_pruned=tuple(pruned),
        linked_orphans=tuple(orphans),
    )


def reconcile_doc_records(workspace: Workspace) -> ReconciliationSummary:
    """Repair existing records without creating records for never-recorded docs."""
    summary = ReconciliationSummary()
    changed_records: list[dict[str, Any]] = []
    for indexed_record in iter_doc_records(workspace):
        doc_path = str(indexed_record.get("doc_path", ""))
        raw_record = load_doc_record(workspace, doc_path, indexed_sections={}) or indexed_record
        updated, report = reconcile_doc_record(workspace, raw_record)
        summary.reports.append(report)
        summary.sections_added += len(report.sections_added)
        summary.sections_refreshed += len(report.sections_refreshed)
        summary.unlinked_sections_pruned += len(report.unlinked_sections_pruned)
        summary.linked_orphans += len(report.linked_orphans)
        if report.changed:
            summary.documents_changed += 1
            changed_records.append(updated)
    if changed_records:
        save_doc_records_batch(workspace, changed_records)
    return summary
