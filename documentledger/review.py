from __future__ import annotations

from typing import Any

from documentledger.doc_index import doc_sections_for_file
from documentledger.errors import DocumentledgerError
from documentledger.impact import (
    ignored_changed_unit_counts,
    relevant_unmapped_changed_units,
    resolve_affected_sections,
)
from documentledger.links import (
    _candidate_ancestors,
    _proposal_links_for_section,
    add_section_link,
    current_source_inventory,
)
from documentledger.models import AmbiguousMatch, ChangedEvidence, CoverageGap, MappingSuggestion, ReviewItem, ReviewPlan, Workspace
from documentledger.scanner import collect_files, run_scan
from documentledger.source_roles import classify_source_role
from documentledger.storage import iter_doc_records, latest_scan

REVIEW_OUTPUT_LIMIT = 40


def _evidence(record: dict[str, Any]) -> ChangedEvidence:
    return ChangedEvidence(
        source_id=str(record.get("source_id", "")),
        source_path=str(record.get("source_path", record.get("path", ""))),
        changed_hashes=tuple(sorted(str(value) for value in record.get("changed_hashes", []) or [])),
        role=classify_source_role({**record, "path": record.get("source_path", record.get("path", ""))}),
    )


def _review_item(record: dict[str, Any]) -> ReviewItem:
    review_action = str(record.get("review_action", "review_required"))
    if review_action not in {"update_required", "review_required", "generated_verify"}:
        review_action = "review_required"
    severity = {"update_required": "high", "review_required": "medium", "generated_verify": "low"}[review_action]
    reasons = {
        "update_required": "Public contract or linked source changed. Update the section and its claims.",
        "review_required": "Tracked implementation changed. Verify that the section remains accurate.",
        "generated_verify": "Generated-reference evidence changed. Rebuild or verify the generated output.",
    }
    return ReviewItem(
        doc_path=str(record.get("doc_path", "")),
        section_id=str(record.get("section_id", "")),
        section_title=str(record.get("summary", "")),
        review_action=review_action,  # type: ignore[arg-type]
        severity=severity,  # type: ignore[arg-type]
        evidence=tuple(_evidence(item) for item in record.get("changed_units", []) or []),
        reasons=(reasons[review_action],),
    )


def _mapping_suggestion(doc_path: str, section_id: str, proposal: dict[str, Any]) -> MappingSuggestion:
    evidence = dict(proposal.get("evidence", {}))
    return MappingSuggestion(
        doc_path=doc_path,
        section_id=section_id,
        source_id=str(proposal.get("source_unit", "")),
        confidence=str(proposal.get("confidence", "")),
        coverage=str(proposal.get("coverage", "")),
        impact=str(proposal.get("impact", "")),
        reason=str(proposal.get("reason", "")),
        evidence_text=str(evidence.get("text", "")),
    )


def _changed_candidate_ids(scan: dict[str, Any]) -> set[str]:
    changed = {str(item.get("source_id", "")) for item in [*(scan.get("changed_units", []) or []), *(scan.get("added_units", []) or [])]}
    result = set(changed)
    for source_id in changed:
        result.update(_candidate_ancestors(source_id))
    return result


def build_review_plan(
    workspace: Workspace,
    *,
    doc_path: str | None = None,
    auto_link: str = "exact",
) -> ReviewPlan:
    if auto_link not in {"exact", "none"}:
        raise DocumentledgerError("invalid_auto_link_policy", "Auto-link policy must be 'exact' or 'none'.")

    run_scan(workspace)
    scan = latest_scan(workspace)
    if scan is None:
        raise DocumentledgerError("scan_missing", "Review could not load the current source scan.")

    doc_paths = collect_files(workspace, workspace.config.doc_roots, workspace.config.doc_extensions)
    if doc_path is not None:
        if doc_path not in doc_paths:
            raise DocumentledgerError("doc_not_found", f"Document is not in the configured documentation roots: {doc_path}")
        doc_paths = [doc_path]

    affected_records = resolve_affected_sections(workspace, scan=scan, docs=doc_paths)
    affected_by_id = {str(item.get("section_id", "")): item for item in affected_records}
    affected_items = tuple(_review_item(item) for item in affected_records)
    unmapped_records = relevant_unmapped_changed_units(workspace, scan=scan)
    ignored_counts = ignored_changed_unit_counts(workspace, scan=scan)
    changed_candidate_ids = _changed_candidate_ids(scan)
    changed_doc_paths = set(scan.get("changed_docs", []) or []) | set(scan.get("added_docs", []) or [])
    inventory = current_source_inventory(workspace)

    section_links: dict[str, list[dict[str, Any]]] = {}
    for record in iter_doc_records(workspace):
        for section in record.get("sections", []) or []:
            section_links[str(section.get("section_id", ""))] = list(section.get("links", []) or [])

    ambiguous_matches = 0
    auto_applied: list[MappingSuggestion] = []
    suggestions: dict[tuple[str, str, str], MappingSuggestion] = {}
    ambiguous_items: dict[tuple[str, str, str, int, int], AmbiguousMatch] = {}
    coverage_gaps: dict[tuple[str, str], CoverageGap] = {}

    for path in doc_paths:
        sections = doc_sections_for_file(workspace.config.root / path, path)
        for section in sections:
            existing_links = section_links.get(section.section_id, [])
            is_unlinked = not existing_links

            doc_changed = path in changed_doc_paths
            is_affected = section.section_id in affected_by_id
            should_review_mappings = bool(unmapped_records)
            if doc_path is None and not (doc_changed or is_affected or is_unlinked or should_review_mappings):
                continue

            proposals, stats = _proposal_links_for_section(
                section.text,
                inventory,
                doc_path=path,
                section_id=section.section_id,
            )
            if is_unlinked and not proposals and not int(stats.get("ambiguous_matches", 0)):
                coverage_gaps[(path, section.section_id)] = CoverageGap(
                    path,
                    section.section_id,
                    section.summary,
                    "No source dependency could be inferred for this documentation section.",
                )
            ambiguous_matches += int(stats.get("ambiguous_matches", 0))
            for match in stats.get("ambiguous_evidence", []):
                span = tuple(int(value) for value in match["span"])
                item = AmbiguousMatch(path, section.section_id, str(match["text"]), span)
                key = (path, section.section_id, item.evidence_text, span[0], span[1])
                ambiguous_items[key] = item
            linked_ids = {str(link.get("source_id", "")) for link in existing_links}
            for proposal in proposals:
                source_id = str(proposal.get("source_unit", ""))
                if source_id in linked_ids:
                    continue
                proposal_is_changed = source_id in changed_candidate_ids
                if not (doc_changed or is_unlinked or doc_path is not None) and not proposal_is_changed:
                    continue
                suggestion = _mapping_suggestion(path, section.section_id, proposal)
                if auto_link == "exact" and proposal.get("auto_applicable") is True:
                    add_section_link(
                        workspace,
                        path,
                        section.heading_slug,
                        source_id,
                        suggestion.coverage,
                        suggestion.impact,
                        suggestion.reason,
                        list(proposal.get("tracked_hashes", []) or []),
                    )
                    auto_applied.append(
                        MappingSuggestion(
                            doc_path=suggestion.doc_path,
                            section_id=suggestion.section_id,
                            source_id=suggestion.source_id,
                            confidence=suggestion.confidence,
                            coverage=suggestion.coverage,
                            impact=suggestion.impact,
                            reason=suggestion.reason,
                            evidence_text=suggestion.evidence_text,
                            auto_applied=True,
                        )
                    )
                    linked_ids.add(source_id)
                else:
                    suggestions[(path, section.section_id, source_id)] = suggestion

    affected_records = resolve_affected_sections(workspace, scan=scan, docs=doc_paths)
    affected_items = tuple(_review_item(item) for item in affected_records)
    unmapped_records = relevant_unmapped_changed_units(workspace, scan=scan)
    ignored_counts = ignored_changed_unit_counts(workspace, scan=scan)
    state = "review_required" if affected_items or unmapped_records or suggestions or ambiguous_matches or coverage_gaps else "clean"
    if affected_items and (unmapped_records or suggestions or ambiguous_matches or coverage_gaps):
        next_action = {
            "kind": "review_and_update",
            "command": "resolve mapping suggestions, update affected sections, then run `documentledger finish`",
        }
    elif affected_items:
        next_action = {
            "kind": "update_docs",
            "command": "update affected sections, then run `documentledger finish`",
        }
    elif unmapped_records or suggestions or ambiguous_matches or coverage_gaps:
        next_action = {
            "kind": "review_mappings",
            "command": "review mapping suggestions, then run `documentledger finish`",
        }
    else:
        next_action = {"kind": "finish", "command": "run `documentledger finish`"}

    return ReviewPlan(
        scan_version=int(scan.get("version", 0)),
        state=state,
        affected=affected_items,
        unmapped_relevant=tuple(_evidence(item) for item in unmapped_records),
        mapping_suggestions=tuple(suggestions[key] for key in sorted(suggestions)),
        coverage_gaps=tuple(coverage_gaps[key] for key in sorted(coverage_gaps)),
        auto_applied=tuple(auto_applied),
        ambiguous_items=tuple(ambiguous_items[key] for key in sorted(ambiguous_items)),
        ambiguous_match_count=ambiguous_matches,
        ignored_change_counts=ignored_counts,
        next_action=next_action,
    )


def review_human_summary(plan: ReviewPlan) -> str:
    lines = [f"Review: {plan.state} (scan {plan.scan_version})"]
    lines.append(
        f"Affected sections: {len(plan.affected)}. Relevant unmapped changes: {len(plan.unmapped_relevant)}. "
        f"Exact links added: {len(plan.auto_applied)}. Suggestions requiring review: {len(plan.mapping_suggestions)}. "
        f"Unmapped sections: {len(plan.coverage_gaps)}."
    )
    for item in plan.affected[:REVIEW_OUTPUT_LIMIT]:
        lines.append(f"  {item.review_action}: {item.doc_path} [{item.section_title}]")
    for gap in plan.coverage_gaps[:REVIEW_OUTPUT_LIMIT]:
        lines.append(f"  unresolved coverage: {gap.doc_path} [{gap.section_title}]")
    for suggestion in plan.mapping_suggestions[:REVIEW_OUTPUT_LIMIT]:
        lines.append(f"  mapping review: {suggestion.doc_path} -> {suggestion.source_id} ({suggestion.confidence})")
    if plan.ambiguous_match_count:
        lines.append(f"Ambiguous symbol matches: {plan.ambiguous_match_count}.")
        for item in plan.ambiguous_items[:REVIEW_OUTPUT_LIMIT]:
            lines.append(f"  ambiguous symbol: {item.doc_path} [{item.evidence_text}]")
    if plan.ignored_change_counts:
        ignored = ", ".join(f"{role}={count}" for role, count in sorted(plan.ignored_change_counts.items()))
        lines.append(f"Ignored changed units: {ignored}.")
    lines.append(f"Next: {plan.next_action['command']}")
    return "\n".join(lines)
