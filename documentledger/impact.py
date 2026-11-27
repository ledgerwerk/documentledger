from __future__ import annotations

from typing import Any

from documentledger.models import Workspace
from documentledger.source_index import file_unit_id
from documentledger.source_roles import classify_source_role, mapping_review_roles
from documentledger.storage import iter_doc_records, latest_scan

GENERATED_COVERAGE = {"api-autodoc", "generated-reference"}

PUBLIC_CHANGE_HASHES = {"decorator_hash", "docstring_hash", "file_hash", "public_contract_hash", "signature_hash"}


def review_action_for(changed_links: list[dict[str, Any]]) -> str:
    if changed_links and all(link["coverage"] in GENERATED_COVERAGE for link in changed_links):
        return "generated_verify"
    if any(link.get("change_type") == "deleted" or set(link.get("changed_hashes", [])) & PUBLIC_CHANGE_HASHES for link in changed_links):
        return "update_required"
    return "review_required"


def legacy_action_for(review_action: str) -> str:
    return "verify-generated-reference" if review_action == "generated_verify" else "rewrite-section"


def with_legacy_action(section: dict[str, Any]) -> dict[str, Any]:
    return section | {"action": legacy_action_for(str(section.get("review_action", "review_required")))}


def link_mismatches(
    link: dict[str, Any],
    source_units: dict[str, dict[str, Any]],
    changed_sources: set[str],
    deleted_sources: set[str],
) -> dict[str, Any] | None:
    source_id = str(link.get("source_id", ""))
    source_path = str(link.get("source_path", ""))
    tracked_hashes = {str(key): str(value) for key, value in dict(link.get("tracked_hashes", {})).items()}
    unit = source_units.get(source_id)
    if unit is None:
        if source_path in deleted_sources or source_id.startswith("py:file:"):
            return {
                "source_id": source_id,
                "source_path": source_path,
                "coverage": str(link.get("coverage", "")),
                "impact": str(link.get("impact", "")),
                "reason": str(link.get("reason", "")),
                "change_type": "deleted",
                "changed_hashes": sorted(tracked_hashes) or ["file_hash"],
                "line_span": [0, 0],
            }
        return None
    mismatched = sorted(name for name, value in tracked_hashes.items() if str(unit.get("hashes", {}).get(name, "")) != value)
    if not mismatched and not tracked_hashes and source_path in changed_sources:
        mismatched = ["file_hash"]
    if not mismatched:
        return None
    return {
        "source_id": source_id,
        "source_path": source_path,
        "coverage": str(link.get("coverage", "")),
        "impact": str(link.get("impact", "")),
        "reason": str(link.get("reason", "")),
        "change_type": "modified",
        "changed_hashes": mismatched,
        "line_span": list(unit.get("line_span", [0, 0])),
    }


def resolve_affected_sections(
    workspace: Workspace,
    scan: dict[str, Any] | None = None,
    docs: list[str] | None = None,
    section_id: str | None = None,
) -> list[dict[str, Any]]:
    scan_record = scan or latest_scan(workspace)
    if scan_record is None:
        return []
    selected_docs = set(docs) if docs is not None else None
    changed_sources = set(scan_record.get("changed_sources", []) or [])
    deleted_sources = set(scan_record.get("deleted_sources", []) or [])
    source_units = dict(scan_record.get("source_units", {}))
    scan_version = int(scan_record.get("version", 0))
    delta_units = [*(scan_record.get("changed_units", []) or []), *(scan_record.get("added_units", []) or [])]
    delta_units_by_id = {str(unit.get("source_id", "")): unit for unit in delta_units}
    delta_units_by_path: dict[str, list[dict[str, Any]]] = {}
    for unit in delta_units:
        delta_units_by_path.setdefault(str(unit.get("path", "")), []).append(unit)
    affected: list[dict[str, Any]] = []
    for record in iter_doc_records(workspace):
        doc_path = str(record.get("doc_path", ""))
        if selected_docs is not None and doc_path not in selected_docs:
            continue
        for section in record.get("sections", []) or []:
            if section_id is not None and str(section.get("heading_slug")) != section_id and str(section.get("section_id")) != section_id:
                continue
            freshness = dict(section.get("freshness", {}) or {})
            freshness_scan_version = int(freshness.get("source_scan_version", 0) or 0)
            needs_current_delta_review = freshness_scan_version < scan_version
            changed_links: list[dict[str, Any]] = []
            for link in section.get("links", []) or []:
                link_record = dict(link)
                mismatch = link_mismatches(link_record, source_units, changed_sources, deleted_sources)
                if mismatch is None and needs_current_delta_review:
                    source_id = str(link_record.get("source_id", ""))
                    source_path = str(link_record.get("source_path", ""))
                    delta_unit = delta_units_by_id.get(source_id)
                    if delta_unit is None and source_id.startswith("py:file:"):
                        path_units = delta_units_by_path.get(source_path, [])
                        delta_unit = path_units[0] if path_units else None
                    if delta_unit is not None:
                        mismatch = {
                            "source_id": source_id,
                            "source_path": source_path,
                            "coverage": str(link_record.get("coverage", "")),
                            "impact": str(link_record.get("impact", "")),
                            "reason": str(link_record.get("reason", "")),
                            "change_type": str(delta_unit.get("change_type", "modified")),
                            "changed_hashes": list(delta_unit.get("changed_hashes", []) or ["file_hash"]),
                            "line_span": list(delta_unit.get("new_line_span", [0, 0])),
                        }
                if mismatch is not None:
                    changed_links.append(mismatch)
            if not changed_links:
                continue
            review_action = review_action_for(changed_links)
            affected.append(
                {
                    "doc_path": doc_path,
                    "section_id": str(section.get("section_id", "")),
                    "heading_path": list(section.get("heading_path", []) or []),
                    "heading_slug": str(section.get("heading_slug", "")),
                    "line_span": list(section.get("line_span", [0, 0])),
                    "section_hash": str(section.get("section_hash", "")),
                    "summary": str(section.get("summary", "")),
                    "review_action": review_action,
                    "changed_units": changed_links,
                }
            )
    return sorted(affected, key=lambda item: (str(item["doc_path"]), str(item["section_id"])))


def stale_doc_details(workspace: Workspace, scan: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    affected = resolve_affected_sections(workspace, scan=scan)
    grouped: dict[str, dict[str, Any]] = {}
    for item in affected:
        doc_path = str(item["doc_path"])
        detail = grouped.setdefault(
            doc_path,
            {"doc_path": doc_path, "affected_sections": [], "changed_sources": set(), "deleted_sources": set()},
        )
        detail["affected_sections"].append(
            {
                "section_id": item["section_id"],
                "heading_path": item["heading_path"],
                "line_span": item["line_span"],
                "action": legacy_action_for(str(item["review_action"])),
                "review_action": item["review_action"],
            }
        )
        for unit in item.get("changed_units", []) or []:
            if unit.get("change_type") == "deleted":
                detail["deleted_sources"].add(str(unit["source_path"]))
            else:
                detail["changed_sources"].add(str(unit["source_path"]))
    return [
        {
            "doc_path": doc_path,
            "affected_sections": detail["affected_sections"],
            "changed_sources": sorted(detail["changed_sources"]),
            "deleted_sources": sorted(detail["deleted_sources"]),
        }
        for doc_path, detail in sorted(grouped.items())
    ]


def unmapped_changed_units(workspace: Workspace, scan: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    scan_record = scan or latest_scan(workspace)
    if scan_record is None:
        return []
    linked_source_ids = {
        str(link.get("source_id", ""))
        for record in iter_doc_records(workspace)
        for section in (record.get("sections", []) or [])
        for link in (section.get("links", []) or [])
    }
    unmapped: list[dict[str, Any]] = []
    for item in [*(scan_record.get("changed_units", []) or []), *(scan_record.get("added_units", []) or [])]:
        source_id = str(item.get("source_id", ""))
        path = str(item.get("path", ""))
        if source_id in linked_source_ids or file_unit_id(path) in linked_source_ids:
            continue
        record = dict(item)
        record["source_role"] = classify_source_role(record)
        unmapped.append(record)
    return unmapped


def relevant_unmapped_changed_units(workspace: Workspace, scan: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    review_roles = mapping_review_roles(workspace)
    return [item for item in unmapped_changed_units(workspace, scan) if item["source_role"] in review_roles]


def ignored_changed_unit_counts(workspace: Workspace, scan: dict[str, Any] | None = None) -> dict[str, int]:
    review_roles = mapping_review_roles(workspace)
    counts: dict[str, int] = {}
    for item in unmapped_changed_units(workspace, scan):
        role = str(item["source_role"])
        if role not in review_roles:
            counts[role] = counts.get(role, 0) + 1
    return dict(sorted(counts.items()))


def linked_source_map(workspace: Workspace) -> dict[str, list[str]]:
    mapping: dict[str, set[str]] = {}
    for record in iter_doc_records(workspace):
        doc_path = str(record.get("doc_path", ""))
        for source in record.get("linked_sources", []) or []:
            mapping.setdefault(str(source), set()).add(doc_path)
    return {source: sorted(docs) for source, docs in mapping.items()}
