"""Current-content documentation validation and completion signals."""

from __future__ import annotations

import json
import shlex
import subprocess
from pathlib import Path
from typing import Any

from ledgercore.hashing import sha256_text

from documentledger.doc_index import doc_sections_for_file
from documentledger.errors import DocumentledgerError
from documentledger.identity import normalize_repo_path
from documentledger.links import audit_links, current_source_inventory
from documentledger.scanner import collect_files, hash_paths
from documentledger.storage import (
    iter_doc_records,
    latest_scan,
    next_state_version,
    save_metadata,
    set_state_version,
    workspace_root,
)

ATTESTATION_SCHEMA = "documentledger.validation-attestation.v1"


def _json_hash(value: Any) -> str:
    return sha256_text(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _sphinx_root(workspace: Any) -> Path | None:
    root = workspace_root(workspace)
    for doc_root in workspace.config.doc_roots:
        candidate = root / doc_root
        if candidate.is_dir() and (candidate / "conf.py").is_file():
            return candidate
    conventional = root / "docs"
    return conventional if (conventional / "conf.py").is_file() else None


def _sphinx_build_configured(commands: list[str], sphinx_root: Path | None) -> bool:
    if sphinx_root is None:
        return True
    return any("sphinx" in command.casefold() for command in commands)


def _target_key(value: str) -> str:
    target = value.strip().replace("\\", "/").strip("`*")
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1]
    for suffix in (".md", ".rst"):
        if target.casefold().endswith(suffix):
            target = target[: -len(suffix)]
            break
    return target.removeprefix("./").rstrip("/")


def _toctree_targets(path: Path) -> set[str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return set()
    targets: set[str] = set()
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        if stripped == ".. toctree::":
            directive_indent = len(lines[index]) - len(lines[index].lstrip())
            index += 1
            while index < len(lines):
                line = lines[index]
                value = line.strip()
                if value and len(line) - len(line.lstrip()) <= directive_indent:
                    break
                if value and not value.startswith(":"):
                    if "<" in value and ">" in value:
                        value = value.rsplit("<", 1)[1].split(">", 1)[0]
                    else:
                        value = value.split()[0]
                    targets.add(_target_key(value))
                index += 1
            continue
        if stripped.casefold().startswith(("```{toctree}", "~~~{toctree}")):
            fence = stripped[:3]
            index += 1
            while index < len(lines) and not lines[index].strip().startswith(fence):
                value = lines[index].strip()
                if value and not value.startswith(":"):
                    if "<" in value and ">" in value:
                        value = value.rsplit("<", 1)[1].split(">", 1)[0]
                    else:
                        value = value.split()[0]
                    targets.add(_target_key(value))
                index += 1
        index += 1
    return targets


def _effective_requirements(
    workspace: Any,
    required_pages: list[str] | None,
    navigation_targets: list[str] | None,
    prior_attestation: dict[str, Any] | None = None,
) -> tuple[list[str], list[str]]:
    sphinx_root = _sphinx_root(workspace)
    pages = set(required_pages or [])
    targets = set(navigation_targets or [])
    if sphinx_root is not None:
        root = workspace_root(workspace)
        index_candidates = [sphinx_root / "index.md", sphinx_root / "index.rst"]
        index_path = next((path for path in index_candidates if path.is_file()), index_candidates[0])
        pages.add(index_path.relative_to(root).as_posix())
        for suffix in (".md", ".rst"):
            changelog = sphinx_root / f"changelog{suffix}"
            if changelog.is_file():
                targets.add("changelog")
                break
    if prior_attestation:
        pages.update(str(value) for value in prior_attestation.get("required_pages", []) or [])
        targets.update(str(value) for value in prior_attestation.get("navigation_targets", []) or [])
    normalized_pages = sorted({normalize_repo_path(page) for page in pages})
    normalized_targets = sorted({_target_key(target) for target in targets if target.strip()})
    return normalized_pages, normalized_targets


def _requirement_issues(workspace: Any, required_pages: list[str], navigation_targets: list[str]) -> list[dict[str, str]]:
    root = workspace_root(workspace)
    issues: list[dict[str, str]] = []
    for doc_path in required_pages:
        target = root / doc_path
        if not target.is_file() or target.stat().st_size == 0:
            issues.append({"code": "required_page_missing", "message": f"Required documentation page is missing or empty: {doc_path}"})
    if not navigation_targets:
        return issues
    sphinx_root = _sphinx_root(workspace)
    if sphinx_root is None:
        return issues + [
            {
                "code": "sphinx_config_missing",
                "message": "Navigation requirements were selected, but no Sphinx conf.py was found.",
            }
        ]
    root_relative = sphinx_root.relative_to(root).as_posix()
    indexed_targets: set[str] = set()
    for extension in workspace.config.doc_extensions:
        if extension not in {".md", ".rst"}:
            continue
        for doc_path in collect_files(workspace, [root_relative], [extension]):
            indexed_targets.update(_toctree_targets(root / doc_path))
    for target in navigation_targets:
        normalized = target
        if normalized.startswith(root_relative + "/"):
            normalized = normalized[len(root_relative) + 1 :]
        normalized = _target_key(normalized)
        candidates = {normalized, f"{normalized}/index"}
        if not candidates.intersection(indexed_targets):
            issues.append({"code": "navigation_target_missing", "message": f"Sphinx toctree does not include required target: {target}"})
        target_files = [sphinx_root / f"{normalized}{suffix}" for suffix in (".md", ".rst")]
        if not any(path.is_file() and path.stat().st_size > 0 for path in target_files):
            issues.append({"code": "navigation_page_missing", "message": f"Required navigation target has no non-empty page: {target}"})
    return issues


def _validation_snapshot(workspace: Any) -> dict[str, Any]:
    source_paths = collect_files(workspace, list(workspace.config.source_roots), list(workspace.config.source_extensions))
    document_paths = collect_files(workspace, list(workspace.config.doc_roots), list(workspace.config.doc_extensions))
    source_hashes = hash_paths(workspace, source_paths)
    document_hashes = hash_paths(workspace, document_paths)
    root = workspace_root(workspace)
    sphinx_root = _sphinx_root(workspace)
    config_paths = {workspace.config.path}
    if sphinx_root is not None:
        config_paths.add(sphinx_root / "conf.py")
        requirements = sphinx_root / "requirements.txt"
        if requirements.is_file():
            config_paths.add(requirements)
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        config_paths.add(pyproject)
    config_file_hashes: dict[str, str] = {}
    for path in sorted(config_paths, key=lambda item: item.as_posix()):
        try:
            path_key = path.relative_to(root).as_posix()
        except ValueError:
            path_key = path.as_posix()
        try:
            config_file_hashes[path_key] = sha256_text(path.read_bytes().hex())
        except OSError:
            config_file_hashes[path_key] = "missing-or-unreadable"
    scan = latest_scan(workspace)
    scan_source_hashes = dict((scan or {}).get("source_hashes", {}) or {})
    scan_document_hashes = dict((scan or {}).get("doc_hashes", {}) or {})
    commands = list(workspace.config.validation_commands)
    return {
        "source_hash": _json_hash(source_hashes),
        "document_hash": _json_hash(document_hashes),
        "config_hash": _json_hash(
            {
                "files": config_file_hashes,
                "source_roots": list(workspace.config.source_roots),
                "doc_roots": list(workspace.config.doc_roots),
                "source_extensions": list(workspace.config.source_extensions),
                "doc_extensions": list(workspace.config.doc_extensions),
                "validation_commands": commands,
                "require_doc_frontmatter": bool(workspace.config.require_doc_frontmatter),
            }
        ),
        "scan_version": int((scan or {}).get("version", 0)),
        "source_index_hash": str((scan or {}).get("source_index_hash", "")),
        "scan_matches_current": bool(scan) and scan_source_hashes == source_hashes and scan_document_hashes == document_hashes,
    }


def _classify_document(
    workspace: Any,
    doc_path: str,
    sections: list[Any],
    record: dict[str, Any] | None,
    scan_version: int,
) -> dict[str, Any]:
    linked_by_id = {str(section.get("section_id", "")): section for section in (record or {}).get("sections", []) or []}
    linked_sections = [bool(list(linked_by_id.get(section.section_id, {}).get("links", []) or [])) for section in sections]
    if linked_sections and all(linked_sections):
        return {"doc_path": doc_path, "state": "linked"}
    has_any_links = any(linked_sections)
    resolution = dict((record or {}).get("coverage_resolution", {}) or {})
    current_hash = hash_paths(workspace, [doc_path]).get(doc_path, "")
    if (
        not has_any_links
        and resolution.get("state") == "intentionally_unlinked"
        and int(resolution.get("scan_version", 0)) == scan_version
        and str(resolution.get("content_hash", "")) == current_hash
    ):
        return {
            "doc_path": doc_path,
            "state": "intentionally_unlinked",
            "reason": str(resolution.get("reason", "")),
        }
    return {"doc_path": doc_path, "state": "unresolved"}


def coverage_metrics(workspace: Any) -> dict[str, Any]:
    docs = collect_files(workspace, list(workspace.config.doc_roots), list(workspace.config.doc_extensions))
    records = {str(record.get("doc_path", "")): record for record in iter_doc_records(workspace)}
    sections_total = 0
    sections_linked = 0
    docs_with_records: set[str] = set()
    linked_sources: set[str] = set()
    linked_source_ids: set[str] = set()
    scan = latest_scan(workspace)
    scan_version = int((scan or {}).get("version", 0))
    document_classifications: list[dict[str, Any]] = []
    for doc_path in docs:
        sections = doc_sections_for_file(workspace.config.root / doc_path, doc_path)
        sections_total += len(sections)
        record = records.get(doc_path)
        document_classifications.append(_classify_document(workspace, doc_path, sections, record, scan_version))
        if record is None:
            continue
        docs_with_records.add(doc_path)
        linked_by_id = {str(section.get("section_id", "")): section for section in record.get("sections", []) or []}
        for section in sections:
            stored = linked_by_id.get(section.section_id, {})
            links = list(stored.get("links", []) or [])
            if links:
                sections_linked += 1
            for link in links:
                linked_sources.add(str(link.get("source_path", "")))
                linked_source_ids.add(str(link.get("source_id", "")))
    inventory = current_source_inventory(workspace)
    known_ids = set(inventory)
    linked_known_ids = {source_id for source_id in linked_source_ids if source_id in known_ids}
    source_files = {str(unit.get("path", "")) for unit in inventory.values() if unit.get("path")}
    linked_files = {path for path in linked_sources if path}
    sources_total = len(source_files)
    sources_linked = len(source_files.intersection(linked_files))
    classification_counts = {
        state: sum(1 for item in document_classifications if item["state"] == state)
        for state in ("linked", "intentionally_unlinked", "unresolved")
    }
    return {
        "documents": {
            "total": len(docs),
            "with_records": len(docs_with_records),
            "without_records": max(len(docs) - len(docs_with_records), 0),
            **classification_counts,
            "classifications": document_classifications,
        },
        "sections": {"total": sections_total, "linked": sections_linked, "unlinked": max(sections_total - sections_linked, 0)},
        "sources": {
            "files": sources_total,
            "files_linked": sources_linked,
            "files_unlinked": max(sources_total - sources_linked, 0),
            "units": len(inventory),
            "units_linked": len(linked_known_ids),
            "units_unlinked": max(len(inventory) - len(linked_known_ids), 0),
        },
        "issues": [],
    }


def documentation_status(
    workspace: Any,
    *,
    required_pages: list[str] | None = None,
    navigation_targets: list[str] | None = None,
) -> dict[str, Any]:
    attestation = workspace.metadata.get("validation_attestation")
    attestation = attestation if isinstance(attestation, dict) else None
    pages, targets = _effective_requirements(workspace, required_pages, navigation_targets, attestation)
    requirement_issues = _requirement_issues(workspace, pages, targets)
    snapshot = _validation_snapshot(workspace)
    commands = list(workspace.config.validation_commands)
    attestation_result = str((attestation or {}).get("result", "not_run"))
    stored_snapshot = dict((attestation or {}).get("snapshot", {}) or {})
    same_requirements = pages == list((attestation or {}).get("required_pages", []) or []) and targets == list(
        (attestation or {}).get("navigation_targets", []) or []
    )
    same_commands = commands == list((attestation or {}).get("commands", []) or [])
    sphinx_root = _sphinx_root(workspace)
    sphinx_detected = sphinx_root is not None
    sphinx_required = sphinx_detected or bool(commands)
    validation_configured = bool(commands) and _sphinx_build_configured(commands, sphinx_root)
    verified = (
        validation_configured
        and attestation_result == "passed"
        and stored_snapshot == snapshot
        and same_requirements
        and same_commands
        and not requirement_issues
    )
    if verified:
        validation_state = "passed_current"
    elif attestation_result == "failed" and stored_snapshot == snapshot:
        validation_state = "failed"
    elif attestation_result == "not_configured":
        validation_state = "not_configured"
    elif attestation is None:
        validation_state = "not_run"
    else:
        validation_state = "stale"
    if requirement_issues or (sphinx_required and not verified):
        documentation_state = "incomplete"
    elif sphinx_required:
        documentation_state = "validated"
    else:
        documentation_state = "not_required"
    required_pages_present = not any(issue["code"] == "required_page_missing" for issue in requirement_issues)
    navigation_ready = not any(
        issue["code"].startswith("navigation_") or issue["code"] == "sphinx_config_missing" for issue in requirement_issues
    )
    return {
        "state": documentation_state,
        "sphinx_detected": sphinx_detected,
        "sphinx_build_configured": _sphinx_build_configured(commands, sphinx_root),
        "required_pages": pages,
        "required_pages_present": required_pages_present,
        "navigation_targets": targets,
        "navigation_ready": navigation_ready,
        "validation_configured": validation_configured,
        "validation_state": validation_state,
        "validation_passed": verified,
        "validation_verified_for_current_content": verified,
        "validation_required": sphinx_required,
        "attestation_result": attestation_result,
        "scan_matches_current": bool(snapshot["scan_matches_current"]),
        "hashes": {key: snapshot[key] for key in ("source_hash", "document_hash", "config_hash", "source_index_hash")},
        "issues": requirement_issues,
    }


def _record_attestation(workspace: Any, attestation: dict[str, Any]) -> None:
    workspace.metadata["validation_attestation"] = attestation
    set_state_version(workspace, next_state_version(workspace))
    save_metadata(workspace)


def run_validation(
    workspace: Any,
    *,
    required_pages: list[str] | None = None,
    navigation_targets: list[str] | None = None,
) -> dict[str, Any]:
    pages, targets = _effective_requirements(workspace, required_pages, navigation_targets)
    commands = list(workspace.config.validation_commands)
    snapshot = _validation_snapshot(workspace)
    requirement_issues = _requirement_issues(workspace, pages, targets)
    attestation: dict[str, Any] = {
        "schema": ATTESTATION_SCHEMA,
        "result": "not_configured" if not commands else "failed",
        "snapshot": snapshot,
        "commands": commands,
        "command_hash": _json_hash(commands),
        "required_pages": pages,
        "navigation_targets": targets,
        "command_results": [],
        "issues": requirement_issues,
    }
    sphinx_root = _sphinx_root(workspace)
    if not commands or not _sphinx_build_configured(commands, sphinx_root):
        attestation["result"] = "not_configured"
        if sphinx_root is not None and commands:
            attestation["issues"].append(
                {
                    "code": "sphinx_validation_command_missing",
                    "message": "A Sphinx project requires a configured command that invokes Sphinx.",
                }
            )
        _record_attestation(workspace, attestation)
        return {"state": "not_configured", "configured": False, "passed": False, "attestation": attestation}
    if requirement_issues:
        attestation["failure_reason"] = "documentation_requirements_failed"
        _record_attestation(workspace, attestation)
        raise DocumentledgerError(
            "documentation_requirements_failed",
            "Required pages or Sphinx navigation are incomplete.",
            ["Create the required pages and include each required target in a Sphinx toctree before validating."],
            details={"issues": requirement_issues, "attestation_result": "failed"},
        )

    command_failure: dict[str, Any] | None = None
    for command in commands:
        try:
            argv = shlex.split(command)
            if not argv:
                raise ValueError("validation command is empty")
            completed = subprocess.run(
                argv,
                cwd=workspace_root(workspace),
                capture_output=True,
                text=True,
                check=False,
            )
            command_result = {"command": command, "exit_code": completed.returncode}
            attestation["command_results"].append(command_result)
            if completed.returncode != 0:
                command_failure = command_result
                break
        except (OSError, ValueError) as exc:
            command_failure = {"command": command, "exit_code": None, "error": str(exc)}
            attestation["command_results"].append(command_failure)
            break

    final_snapshot = _validation_snapshot(workspace)
    if command_failure is None and final_snapshot != snapshot:
        command_failure = {"error": "source, documentation, configuration, or scan state changed during validation"}
        attestation["failure_reason"] = "content_changed_during_validation"
    attestation["snapshot"] = final_snapshot
    attestation["result"] = "failed" if command_failure else "passed"
    if command_failure:
        attestation["failure"] = command_failure
    _record_attestation(workspace, attestation)
    if command_failure:
        raise DocumentledgerError(
            "validation_command_failed",
            "One or more configured documentation validation commands failed.",
            ["Review the command result, correct the docs or environment, then rerun `documentledger document validate`."],
            details={"failure": command_failure, "attestation_result": "failed"},
        )
    return {"state": "passed_current", "configured": True, "passed": True, "attestation": attestation}


def completion_status(
    workspace: Any,
    *,
    required_pages: list[str] | None = None,
    navigation_targets: list[str] | None = None,
    health_issues: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    scan = latest_scan(workspace)
    coverage = coverage_metrics(workspace)
    documentation = documentation_status(
        workspace,
        required_pages=required_pages,
        navigation_targets=navigation_targets,
    )
    records = list(iter_doc_records(workspace))
    linked_count = int(coverage["sections"]["linked"])
    mapping_complete = (
        coverage["documents"]["total"] > 0
        and coverage["documents"]["without_records"] == 0
        and coverage["sections"]["total"] > 0
        and coverage["documents"]["unresolved"] == 0
        and coverage["sources"]["units"] > 0
        and coverage["sources"]["units_unlinked"] == 0
        and linked_count > 0
    )
    mapping = {
        "state": "covered" if mapping_complete else "review_required",
        "documents": coverage["documents"],
        "sections": coverage["sections"],
        "sources": coverage["sources"],
        "documents_with_records": len(records),
    }
    blockers: list[str] = []
    if scan is None:
        blockers.append("baseline_scan_missing")
    elif not documentation["scan_matches_current"]:
        blockers.append("scan_not_current_for_source_and_docs")
    if health_issues:
        blockers.append("health_issues_present")
    if not mapping_complete:
        blockers.append("mapping_coverage_incomplete")
    blockers.extend(str(issue["code"]) for issue in documentation["issues"])
    audit = audit_links(workspace)
    if not audit.get("ok", False):
        blockers.append("link_audit_failed")
    try:
        from documentledger.impact import resolve_affected_sections

        if resolve_affected_sections(workspace):
            blockers.append("stale_linked_documentation")
    except DocumentledgerError:
        blockers.append("affected_sections_unresolved")
    if documentation["validation_required"] and not documentation["validation_configured"]:
        blockers.append("validation_not_configured")
    if documentation["validation_required"] and not documentation["validation_verified_for_current_content"]:
        blockers.append("validation_not_verified_for_current_content")
    blockers = list(dict.fromkeys(blockers))
    return {
        "health": {"state": "healthy" if not health_issues else "issues", "issues": list(health_issues or [])},
        "mapping": mapping,
        "documentation": documentation,
        "completion": {"ready": not blockers, "blocking_reasons": blockers},
    }
