"""Review, validate, audit, and record section freshness."""

from __future__ import annotations

from typing import Any

from documentledger.errors import DocumentledgerError
from documentledger.freshness import record_freshness_resolutions
from documentledger.identity import normalize_repo_path
from documentledger.impact import relevant_unmapped_changed_units, resolve_affected_sections
from documentledger.links import audit_links
from documentledger.models import FinishResult, FreshnessResolution, ReviewDecision, ValidationResult, Workspace
from documentledger.review import build_review_plan
from documentledger.storage import doc_record_path, iter_doc_records, latest_scan, read_yaml
from documentledger.verification import documentation_status, run_validation

_VALID_DECISIONS = {"reviewed-no-change", "generated-verified"}


def _decision_key(decision: ReviewDecision) -> tuple[str, str]:
    if decision.disposition not in _VALID_DECISIONS:
        raise DocumentledgerError("decision_invalid", f"Unsupported freshness decision: {decision.disposition!r}.")
    if not decision.reason.strip():
        raise DocumentledgerError("reason_required", f"{decision.disposition} requires a non-empty reason.")
    doc_path = normalize_repo_path(decision.doc_path)
    section_id = decision.section_id.strip()
    if not section_id.startswith("md:section:"):
        section_id = f"md:section:{doc_path}::{section_id}"
    return doc_path, section_id


def _section_hashes(records: list[dict[str, Any]]) -> dict[tuple[str, str], tuple[str, str]]:
    hashes: dict[tuple[str, str], tuple[str, str]] = {}
    for record in records:
        doc_path = str(record.get("doc_path", ""))
        for section in record.get("sections", []) or []:
            section_id = str(section.get("section_id", ""))
            freshness = dict(section.get("freshness", {}) or {})
            baseline = str(freshness.get("section_hash") or section.get("section_hash", ""))
            hashes[(doc_path, section_id)] = (baseline, str(section.get("section_hash", "")))
    return hashes


def _stored_section_hashes(workspace: Workspace) -> dict[tuple[str, str], str]:
    hashes: dict[tuple[str, str], str] = {}
    for record in iter_doc_records(workspace):
        doc_path = str(record.get("doc_path", ""))
        stored = read_yaml(doc_record_path(workspace, doc_path))
        for section in stored.get("sections", []) or []:
            section_id = str(section.get("section_id", ""))
            freshness = dict(section.get("freshness", {}) or {})
            baseline = str(section.get("pending_section_hash") or freshness.get("section_hash") or section.get("section_hash", ""))
            if baseline:
                hashes[(doc_path, section_id)] = baseline
    return hashes


def finish_review(workspace: Workspace, decisions: tuple[ReviewDecision, ...] = ()) -> FinishResult:
    """Run the finish gate and atomically record freshness only after all checks pass."""
    previous_scan = latest_scan(workspace)
    previous_hashes = _stored_section_hashes(workspace)
    previous_affected = resolve_affected_sections(workspace, scan=previous_scan) if previous_scan else []
    previous_unmapped = relevant_unmapped_changed_units(workspace, scan=previous_scan) if previous_scan else []

    plan = build_review_plan(workspace, auto_link="none")
    scan = latest_scan(workspace)
    if scan is None:
        raise DocumentledgerError("scan_missing", "Finish could not load the current source scan.")

    pending_unmapped = {
        str(item.get("source_id", "")): item for item in [*previous_unmapped, *relevant_unmapped_changed_units(workspace, scan=scan)]
    }
    unresolved_mappings = {
        "unmapped_changed_units": list(pending_unmapped.values()),
        "suggestions": [item.to_record() for item in plan.mapping_suggestions],
        "ambiguous_evidence": [item.to_record() for item in plan.ambiguous_items],
        "coverage_gaps": [item.to_record() for item in plan.coverage_gaps],
    }
    if any(unresolved_mappings.values()):
        raise DocumentledgerError(
            "review_required",
            "Finish cannot record freshness while required mapping review remains unresolved.",
            ["Run `documentledger review`, resolve the remaining mappings, and retry finish."],
            details=unresolved_mappings,
        )

    audit = audit_links(workspace)
    if not audit.get("ok", False):
        raise DocumentledgerError(
            "link_audit_failed",
            "Finish link audit failed; no freshness dispositions were recorded.",
            ["Resolve the reported link audit issues and retry finish."],
            details={"issues": list(audit.get("issues", []))},
        )

    current_hashes = _section_hashes(iter_doc_records(workspace))
    actions: dict[tuple[str, str], str] = {}
    for item in previous_affected:
        key = (str(item.get("doc_path", "")), str(item.get("section_id", "")))
        actions[key] = str(item.get("review_action", "review_required"))
    for item in plan.affected:
        actions[(item.doc_path, item.section_id)] = item.review_action

    decision_map: dict[tuple[str, str], ReviewDecision] = {}
    for decision in decisions:
        key = _decision_key(decision)
        if key in decision_map:
            raise DocumentledgerError("decision_invalid", f"More than one decision was supplied for {key[0]} [{key[1]}].")
        decision_map[key] = decision

    resolutions: list[FreshnessResolution] = []
    unused_decisions = dict(decision_map)
    scan_version = int(scan.get("version", 0))
    for key, action in sorted(actions.items()):
        doc_path, section_id = key
        if key not in current_hashes:
            raise DocumentledgerError("section_not_found", f"Affected section no longer exists: {doc_path} [{section_id}].")
        baseline_hash = previous_hashes.get(key, current_hashes[key][1])
        current_hash = current_hashes[key][1]
        if baseline_hash != current_hash:
            disposition = "updated"
            reason = ""
        else:
            decision = decision_map.get(key)
            if decision is None:
                raise DocumentledgerError(
                    "freshness_decision_required",
                    f"Affected section needs an explicit freshness decision: {doc_path} [{section_id}].",
                    ["Edit the section or pass --reviewed-no-change / --generated-verified with a reason."],
                    details={"doc_path": doc_path, "section_id": section_id, "review_action": action},
                )
            expected = "generated-verified" if action == "generated_verify" else "reviewed-no-change"
            if decision.disposition != expected:
                raise DocumentledgerError(
                    "decision_invalid",
                    f"{doc_path} [{section_id}] requires the {expected} disposition.",
                )
            disposition = decision.disposition
            reason = decision.reason
            unused_decisions.pop(key, None)
        resolutions.append(FreshnessResolution(doc_path, section_id, disposition, reason, scan_version, current_hash))

    if unused_decisions:
        key = min(unused_decisions)
        raise DocumentledgerError(
            "decision_not_applicable",
            f"No unchanged affected section requires the supplied decision: {key[0]} [{key[1]}].",
        )

    validation_result = run_validation(workspace)
    attestation = dict(validation_result.get("attestation", {}))
    documentation = documentation_status(workspace)
    if documentation["validation_required"] and not documentation["validation_verified_for_current_content"]:
        raise DocumentledgerError(
            "validation_not_configured",
            "Finish requires a current validation attestation for this documentation project.",
            ["Configure and run the required documentation validation command before retrying finish."],
            details={"attestation_result": attestation.get("result"), "issues": attestation.get("issues", [])},
        )
    validation = tuple(
        ValidationResult(str(item["command"]), int(item.get("exit_code") or 0), "")
        for item in attestation.get("command_results", [])
        if "command" in item
    )

    resolved = tuple(resolutions)
    record_freshness_resolutions(workspace, resolved)
    return FinishResult(scan_version, resolved, validation, True)
