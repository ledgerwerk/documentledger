from __future__ import annotations

from pathlib import Path
from typing import Any

from documentledger.doc_index import doc_sections_for_file, whole_doc_section
from documentledger.errors import DocumentledgerError
from documentledger.identity import normalize_repo_path
from documentledger.models import Workspace
from documentledger.scanner import collect_files
from documentledger.source_index import file_unit_id, source_inventory
from documentledger.storage import iter_doc_records, latest_scan, load_doc_record, read_yaml, save_doc_record

VALID_COVERAGE = {
    "cli-command",
    "cli-option",
    "json-contract",
    "error-contract",
    "storage-schema",
    "architecture",
    "api-autodoc",
    "workflow",
    "example",
    "troubleshooting",
    "generated-reference",
    "implementation-note",
    "broad-file-fallback",
}
VALID_IMPACT = {
    "behavior",
    "signature",
    "public-api",
    "schema",
    "example-output",
    "implementation-note",
    "generated-docs",
    "unknown",
}
TRACKED_HASH_DEFAULTS = {
    "api-autodoc": ["signature_hash", "docstring_hash"],
    "generated-reference": ["signature_hash", "docstring_hash"],
    "cli-command": ["signature_hash", "decorator_hash", "public_contract_hash"],
    "cli-option": ["signature_hash", "decorator_hash", "public_contract_hash"],
    "json-contract": ["public_contract_hash"],
    "error-contract": ["public_contract_hash"],
    "storage-schema": ["public_contract_hash"],
    "architecture": ["body_hash", "public_contract_hash"],
    "implementation-note": ["body_hash"],
    "workflow": ["public_contract_hash"],
    "example": ["public_contract_hash"],
    "troubleshooting": ["public_contract_hash"],
    "broad-file-fallback": ["file_hash"],
}


def ensure_extension(path: str, extensions: list[str], kind: str) -> None:
    if Path(path).suffix not in extensions:
        raise DocumentledgerError("invalid_extension", f"{kind} path has an unsupported extension: {path}")


def validate_existing(workspace: Workspace, path: str, extensions: list[str], kind: str) -> str:
    normalized = normalize_repo_path(path)
    ensure_extension(normalized, extensions, kind)
    if not (workspace.config.root / normalized).exists():
        raise DocumentledgerError(f"missing_{kind}", f"{kind.capitalize()} path does not exist: {normalized}")
    return normalized


def current_source_inventory(workspace: Workspace) -> dict[str, dict[str, Any]]:
    scan = latest_scan(workspace)
    if scan is not None and scan.get("source_units"):
        return dict(scan["source_units"])
    source_paths = collect_files(workspace, workspace.config.source_roots, workspace.config.source_extensions)
    return source_inventory(workspace.config.root, source_paths)


def current_doc_sections(workspace: Workspace, doc_path: str) -> list[dict[str, Any]]:
    target = workspace.config.root / doc_path
    sections = doc_sections_for_file(target, doc_path)
    return [section.to_record() for section in sections]


def ensure_valid_enum(value: str, valid_values: set[str], field: str) -> str:
    if value not in valid_values:
        raise DocumentledgerError("invalid_enum", f"Invalid {field}: {value}")
    return value


def find_section(workspace: Workspace, doc_path: str, section_ref: str) -> dict[str, Any]:
    sections = current_doc_sections(workspace, doc_path)
    for section in sections:
        if str(section["section_id"]) == section_ref or str(section["heading_slug"]) == section_ref:
            return section
    raise DocumentledgerError("section_not_found", f"No section {section_ref} exists in {doc_path}")


def record_for_doc(workspace: Workspace, doc_path: str) -> dict[str, Any]:
    return load_doc_record(workspace, doc_path) or {
        "schema": "documentledger.doc_record.v4",
        "doc_path": doc_path,
        "linked_sources": [],
        "sections": [],
        "last_fresh_scan_version": 0,
        "last_fresh_hash": "",
        "notes": "",
        "version": 0,
    }


def ensure_section_entry(record: dict[str, Any], section_meta: dict[str, Any]) -> dict[str, Any]:
    for section in record.get("sections", []) or []:
        if str(section.get("section_id")) == str(section_meta.get("section_id")):
            section["heading_path"] = list(section_meta.get("heading_path", []) or [])
            section["heading_slug"] = str(section_meta.get("heading_slug", ""))
            section["line_span"] = list(section_meta.get("line_span", [1, 1]))
            section["section_hash"] = str(section_meta.get("section_hash", ""))
            section["summary"] = str(section_meta.get("summary", ""))
            section.setdefault("links", [])
            return section
    new_section = dict(section_meta)
    new_section["links"] = list(new_section.get("links", []) or [])
    record.setdefault("sections", []).append(new_section)
    return new_section


def refresh_linked_sources(record: dict[str, Any]) -> None:
    record["linked_sources"] = sorted(
        {
            str(link.get("source_path", ""))
            for section in (record.get("sections", []) or [])
            for link in (section.get("links", []) or [])
            if str(link.get("source_path", ""))
        }
    )


def source_unit_record(workspace: Workspace, source_unit: str) -> dict[str, Any]:
    inventory = current_source_inventory(workspace)
    if source_unit not in inventory:
        raise DocumentledgerError("source_unit_not_found", f"Unknown source unit: {source_unit}")
    return dict(inventory[source_unit])


def edge_tracked_hashes(unit: dict[str, Any], coverage: str, tracked_hash_names: list[str] | None = None) -> dict[str, str]:
    names = tracked_hash_names or TRACKED_HASH_DEFAULTS.get(coverage, ["file_hash"])
    hashes = dict(unit.get("hashes", {}))
    return {name: str(hashes[name]) for name in names if name in hashes}


def add_edge(section: dict[str, Any], edge: dict[str, Any], replace: bool = False) -> bool:
    links = list(section.get("links", []) or [])
    edge_key = (edge["source_id"], edge["coverage"], edge["impact"])
    existing_keys = {(str(item.get("source_id")), str(item.get("coverage")), str(item.get("impact"))) for item in links}
    if edge_key in existing_keys:
        return False
    if replace:
        links = []
    links.append(edge)
    section["links"] = sorted(links, key=lambda item: (str(item["source_path"]), str(item["source_id"]), str(item["coverage"])))
    return True


def add_link(workspace: Workspace, doc: str, source: str, reason: str | None = None) -> dict[str, object]:
    doc_path = validate_existing(workspace, doc, workspace.config.doc_extensions, "doc")
    source_path = validate_existing(workspace, source, workspace.config.source_extensions, "source")
    record = record_for_doc(workspace, doc_path)
    doc_text = (workspace.config.root / doc_path).read_text(encoding="utf-8")
    section = ensure_section_entry(record, whole_doc_section(doc_path, doc_text).to_record())
    unit = source_unit_record(workspace, file_unit_id(source_path))
    edge = {
        "source_id": file_unit_id(source_path),
        "source_path": source_path,
        "coverage": "broad-file-fallback",
        "impact": "unknown",
        "reason": reason or "Broad file fallback link.",
        "tracked_hashes": edge_tracked_hashes(unit, "broad-file-fallback"),
    }
    before = str(record)
    changed = add_edge(section, edge)
    if reason:
        record["notes"] = reason
    refresh_linked_sources(record)
    if changed or str(record) != before:
        save_doc_record(workspace, record)
        saved = load_doc_record(workspace, doc_path)
        return saved or record
    return record


def remove_link(workspace: Workspace, doc: str, source: str) -> dict[str, object]:
    doc_path = normalize_repo_path(doc)
    source_path = normalize_repo_path(source)
    record = load_doc_record(workspace, doc_path)
    if record is None:
        raise DocumentledgerError("doc_record_missing", f"No doc record exists for {doc_path}")
    before = str(record)
    for section in record.get("sections", []) or []:
        section["links"] = [
            link
            for link in (section.get("links", []) or [])
            if not (str(link.get("source_path")) == source_path and str(link.get("coverage")) == "broad-file-fallback")
        ]
    refresh_linked_sources(record)
    if str(record) != before:
        save_doc_record(workspace, record)
        saved = load_doc_record(workspace, doc_path)
        return saved or record
    return record


def add_section_link(
    workspace: Workspace,
    doc: str,
    section_ref: str,
    source_unit: str,
    coverage: str,
    impact: str,
    reason: str,
    tracked_hash_names: list[str] | None = None,
    replace_section: bool = False,
) -> dict[str, Any]:
    doc_path = validate_existing(workspace, doc, workspace.config.doc_extensions, "doc")
    ensure_valid_enum(coverage, VALID_COVERAGE, "coverage")
    ensure_valid_enum(impact, VALID_IMPACT, "impact")
    section_meta = find_section(workspace, doc_path, section_ref)
    unit = source_unit_record(workspace, source_unit)
    record = record_for_doc(workspace, doc_path)
    section = ensure_section_entry(record, section_meta)
    edge = {
        "source_id": source_unit,
        "source_path": str(unit.get("path", "")),
        "coverage": coverage,
        "impact": impact,
        "reason": reason,
        "tracked_hashes": edge_tracked_hashes(unit, coverage, tracked_hash_names),
    }
    if add_edge(section, edge, replace=replace_section):
        refresh_linked_sources(record)
        save_doc_record(workspace, record)
        saved = load_doc_record(workspace, doc_path)
        return saved or record
    return record


def remove_section_link(workspace: Workspace, doc: str, section_ref: str, source_unit: str) -> dict[str, Any]:
    doc_path = normalize_repo_path(doc)
    record = load_doc_record(workspace, doc_path)
    if record is None:
        raise DocumentledgerError("doc_record_missing", f"No doc record exists for {doc_path}")
    section_meta = find_section(workspace, doc_path, section_ref)
    before = str(record)
    for section in record.get("sections", []) or []:
        if str(section.get("section_id")) != str(section_meta.get("section_id")):
            continue
        section["links"] = [link for link in (section.get("links", []) or []) if str(link.get("source_id")) != source_unit]
    refresh_linked_sources(record)
    if str(record) != before:
        save_doc_record(workspace, record)
        saved = load_doc_record(workspace, doc_path)
        return saved or record
    return record


def import_mapping(workspace: Workspace, file_path: str, apply_changes: bool, replace_section: bool = False) -> dict[str, Any]:
    payload = read_yaml(Path(file_path))
    doc_path = validate_existing(workspace, str(payload.get("doc_path", "")), workspace.config.doc_extensions, "doc")
    sections = list(payload.get("sections", []) or [])
    if not sections:
        raise DocumentledgerError("invalid_mapping", "Mapping file contains no sections.")
    planned = 0
    for section in sections:
        section_ref = str(section.get("section") or section.get("section_id") or "")
        if not section_ref:
            raise DocumentledgerError("invalid_mapping", "Section entry is missing `section`.")
        links = list(section.get("links", []) or [])
        if not links:
            raise DocumentledgerError("invalid_mapping", f"Section {section_ref} contains no links.")
        for link in links:
            coverage = ensure_valid_enum(str(link.get("coverage") or ""), VALID_COVERAGE, "coverage")
            impact = ensure_valid_enum(str(link.get("impact") or ""), VALID_IMPACT, "impact")
            source_unit = str(link.get("source_unit") or link.get("source_id") or "")
            if not source_unit:
                raise DocumentledgerError("invalid_mapping", f"Section {section_ref} is missing a source unit.")
            tracked_hash_names = list(link.get("tracked_hashes", []) or []) or None
            if apply_changes:
                add_section_link(
                    workspace,
                    doc_path,
                    section_ref,
                    source_unit,
                    coverage,
                    impact,
                    str(link.get("reason") or ""),
                    tracked_hash_names=tracked_hash_names,
                    replace_section=replace_section,
                )
            planned += 1
    return {"doc_path": doc_path, "planned_edges": planned, "applied": apply_changes}


def audit_links(workspace: Workspace) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    inventory = current_source_inventory(workspace)
    for record in iter_doc_records(workspace):
        doc_path = str(record.get("doc_path", ""))
        try:
            sections = {section["section_id"] for section in current_doc_sections(workspace, doc_path)}
        except DocumentledgerError as exc:
            issues.append({"code": exc.code, "message": exc.message})
            continue
        for section in record.get("sections", []) or []:
            section_id = str(section.get("section_id", ""))
            if section_id not in sections:
                issues.append({"code": "missing_section", "message": f"Missing section: {section_id}"})
            seen_edges: set[tuple[str, str, str]] = set()
            for link in section.get("links", []) or []:
                source_id = str(link.get("source_id", ""))
                edge_key = (source_id, str(link.get("coverage", "")), str(link.get("impact", "")))
                if edge_key in seen_edges:
                    issues.append({"code": "duplicate_edge", "message": f"Duplicate edge: {section_id} -> {source_id}"})
                seen_edges.add(edge_key)
                if source_id not in inventory:
                    issues.append({"code": "missing_source_unit", "message": f"Missing source unit: {source_id}"})
    return {"ok": not issues, "issues": issues}


def list_links(workspace: Workspace) -> list[dict[str, object]]:
    return iter_doc_records(workspace)


def docs_for_source(workspace: Workspace, source: str) -> list[str]:
    normalized = normalize_repo_path(source)
    return sorted(
        str(record["doc_path"]) for record in iter_doc_records(workspace) if normalized in (record.get("linked_sources", []) or [])
    )
