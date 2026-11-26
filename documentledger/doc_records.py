"""Durable document-record reconciliation against the live Markdown index."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from difflib import SequenceMatcher
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
    "body_hash",
    "body_length",
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
    sections_renamed: tuple[tuple[str, str], ...] = ()
    possible_renames: tuple[tuple[str, str, str], ...] = ()


@dataclass
class ReconciliationSummary:
    documents_changed: int = 0
    sections_added: int = 0
    sections_refreshed: int = 0
    unlinked_sections_pruned: int = 0
    linked_orphans: int = 0
    sections_renamed: int = 0
    possible_section_renames: list[dict[str, str]] = field(default_factory=list)
    reports: list[ReconciliationReport] = field(default_factory=list)

    def to_record(self) -> dict[str, Any]:
        return {
            "documents_changed": self.documents_changed,
            "sections_added": self.sections_added,
            "sections_refreshed": self.sections_refreshed,
            "unlinked_sections_pruned": self.unlinked_sections_pruned,
            "linked_orphans": self.linked_orphans,
            "sections_renamed": self.sections_renamed,
            "possible_section_rename_count": len(self.possible_section_renames),
            "possible_section_renames": list(self.possible_section_renames),
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


def _section_rename_matches(
    stored_sections: list[dict[str, Any]],
    current_sections: list[dict[str, Any]],
    stored_by_id: dict[str, dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], set[str], tuple[tuple[str, str, str], ...]]:
    missing = [
        (index, section)
        for index, section in enumerate(stored_sections)
        if str(section.get("section_id", "")) not in {str(item.get("section_id", "")) for item in current_sections}
        and (section.get("links") or section.get("freshness") or section.get("pending_section_hash"))
    ]
    candidates = [
        (index, section) for index, section in enumerate(current_sections) if str(section.get("section_id", "")) not in stored_by_id
    ]
    old_body_counts: dict[str, int] = {}
    current_body_counts: dict[str, int] = {}
    for _, section in missing:
        body_hash = str(section.get("body_hash", ""))
        if body_hash:
            old_body_counts[body_hash] = old_body_counts.get(body_hash, 0) + 1
    for section in current_sections:
        body_hash = str(section.get("body_hash", ""))
        if body_hash:
            current_body_counts[body_hash] = current_body_counts.get(body_hash, 0) + 1

    proposals: dict[str, list[tuple[str, str, bool]]] = {}
    for old_index, old in missing:
        old_id = str(old.get("section_id", ""))
        old_path = list(old.get("heading_path", []) or [])
        old_heading = old_path[-1] if old_path else str(old.get("heading_slug", ""))
        old_hash = str(old.get("body_hash", ""))
        for new_index, current in candidates:
            new_id = str(current.get("section_id", ""))
            new_path = list(current.get("heading_path", []) or [])
            new_heading = new_path[-1] if new_path else str(current.get("heading_slug", ""))
            body_match = bool(old_hash) and old_hash == str(current.get("body_hash", ""))
            previous_match = (
                old_index > 0
                and new_index > 0
                and str(stored_sections[old_index - 1].get("section_id", "")) == str(current_sections[new_index - 1].get("section_id", ""))
            )
            next_match = (
                old_index + 1 < len(stored_sections)
                and new_index + 1 < len(current_sections)
                and str(stored_sections[old_index + 1].get("section_id", "")) == str(current_sections[new_index + 1].get("section_id", ""))
            )
            neighbor_matches = int(previous_match) + int(next_match)
            order_close = abs((old_index + 0.5) / max(len(stored_sections), 1) - (new_index + 0.5) / max(len(current_sections), 1)) <= 0.25
            same_parent = old_path[:-1] == new_path[:-1]
            title_similarity = SequenceMatcher(None, old_heading.casefold(), new_heading.casefold()).ratio()
            if not body_match and not (neighbor_matches and same_parent) and not (same_parent and order_close and title_similarity >= 0.45):
                continue

            if body_match:
                reason = "Body hash matches, but rename evidence is not unique enough to reconcile automatically."
            elif neighbor_matches:
                reason = "Neighboring headings suggest a rename, but the section body changed."
            else:
                reason = "Heading and source order suggest a rename, but the section body changed."
            proposals.setdefault(old_id, []).append((new_id, reason, False))

            unique_body = old_body_counts.get(old_hash, 0) == 1 and current_body_counts.get(old_hash, 0) == 1
            substantial_body = int(old.get("body_length", 0)) >= 32
            high_confidence = body_match and (
                (unique_body and substantial_body and (order_close or neighbor_matches > 0)) or neighbor_matches == 2
            )
            if high_confidence:
                proposals[old_id][-1] = (new_id, "Exact body and neighboring section identity confirm the rename.", True)

    eligible_targets: dict[str, int] = {}
    for matches in proposals.values():
        eligible_ids = {new_id for new_id, _, eligible in matches if eligible}
        for new_id in eligible_ids:
            eligible_targets[new_id] = eligible_targets.get(new_id, 0) + 1

    renamed_by_current: dict[str, dict[str, Any]] = {}
    renamed_old: set[str] = set()
    possible: list[tuple[str, str, str]] = []
    for old_id, matches in proposals.items():
        eligible = [(new_id, reason) for new_id, reason, is_eligible in matches if is_eligible and eligible_targets.get(new_id) == 1]
        if len(eligible) == 1:
            new_id, _ = eligible[0]
            renamed_by_current[new_id] = next(section for section in stored_sections if str(section.get("section_id", "")) == old_id)
            renamed_old.add(old_id)
            continue
        for new_id, reason, _ in matches:
            possible.append((old_id, new_id, reason))
    return renamed_by_current, renamed_old, tuple(possible)


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
    renamed_by_current, renamed_old, possible_renames = _section_rename_matches(stored_sections, current_sections, stored_by_id)
    reconciled: list[dict[str, Any]] = []
    added: list[str] = []
    refreshed: list[str] = []
    pruned: list[str] = []
    orphans: list[str] = []
    renamed: list[tuple[str, str]] = []

    for current in current_sections:
        section_id = str(current["section_id"])
        stored = stored_by_id.get(section_id) or renamed_by_current.get(section_id)
        if stored is None:
            new_section = deepcopy(current)
            new_section["links"] = []
            reconciled.append(new_section)
            added.append(section_id)
            continue
        merged = deepcopy(current)
        if str(current.get("section_hash", "")) != str(stored.get("section_hash", "")):
            previous_freshness = dict(stored.get("freshness", {}) or {})
            merged["pending_section_hash"] = str(
                stored.get("pending_section_hash") or previous_freshness.get("section_hash") or stored.get("section_hash", "")
            )
        elif stored.get("pending_section_hash"):
            merged["pending_section_hash"] = str(stored["pending_section_hash"])
        merged["links"] = deepcopy(list(stored.get("links", []) or []))
        if "freshness" in stored:
            merged["freshness"] = deepcopy(stored["freshness"])
        reconciled.append(merged)
        stored_section_id = str(stored.get("section_id", ""))
        if stored_section_id != section_id:
            renamed.append((stored_section_id, section_id))
        if _metadata(stored) != _metadata(merged):
            refreshed.append(section_id)

    for section_id in sorted(set(stored_by_id) - set(current_by_id)):
        stored = stored_by_id[section_id]
        if section_id in renamed_old:
            continue
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
        sections_renamed=tuple(renamed),
        possible_renames=possible_renames,
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
        summary.sections_renamed += len(report.sections_renamed)
        summary.possible_section_renames.extend(
            {
                "doc_path": doc_path,
                "old_section_id": old_id,
                "candidate_section_id": candidate_id,
                "reason": reason,
            }
            for old_id, candidate_id, reason in report.possible_renames
        )
        if report.changed:
            summary.documents_changed += 1
            changed_records.append(updated)
    if changed_records:
        save_doc_records_batch(workspace, changed_records)
    return summary
