from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from ledgercore.errors import AtomicWriteError
from ledgercore.yamlio import write_yaml as core_write_yaml

from documentledger.doc_index import doc_sections_for_file, whole_doc_section
from documentledger.errors import DocumentledgerError
from documentledger.identity import normalize_repo_path
from documentledger.models import Workspace
from documentledger.output import raise_output_write_error, write_output_file
from documentledger.proposal_manifest import (
    PROPOSAL_MANIFEST_NAME,
    PROPOSAL_MANIFEST_SCHEMA,
    existing_owned_filenames,
    proposal_filename,
    require_current_scan,
)
from documentledger.scanner import collect_files, file_hash
from documentledger.source_index import file_unit_id, source_inventory
from documentledger.storage import (
    iter_doc_records,
    latest_scan,
    load_doc_record,
    read_yaml,
    save_doc_record,
    save_doc_records_batch,
    state_version,
)

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


@dataclass
class PreparedSection:
    section_meta: dict[str, Any]
    edges: list[dict[str, Any]] = field(default_factory=list)
    edge_keys: set[tuple[str, str, str]] = field(default_factory=set)


@dataclass
class PreparedDocument:
    doc_path: str
    record: dict[str, Any]
    sections: dict[str, PreparedSection] = field(default_factory=dict)


@dataclass
class PreparedMappingBatch:
    mapping_paths: list[str]
    documents: dict[str, PreparedDocument]
    planned_edges: int
    empty_mapping_paths: list[str] = field(default_factory=list)

    @property
    def section_count(self) -> int:
        return sum(len(document.sections) for document in self.documents.values())

    @property
    def empty_mapping_count(self) -> int:
        return len(self.empty_mapping_paths)


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


GENERIC_PROPOSAL_NAMES = {"main", "build", "entry", "run", "get", "set", "metadata"}


def _source_role(unit: dict[str, Any]) -> str:
    path = str(unit.get("path", "")).replace("\\", "/")
    parts = path.split("/")
    return "test" if "tests" in parts or path.startswith("test") or Path(path).name.startswith("test_") else "production"


def _markdown_evidence(section_text: str) -> tuple[str, str]:
    fenced = "\n".join(re.findall(r"```[^\n]*\n(.*?)```", section_text, flags=re.DOTALL))
    inline = "\n".join(re.findall(r"(?<!`)`([^`\n]+)`(?!`)", section_text))
    code = "\n".join(part for part in (fenced, inline) if part)
    prose = re.sub(r"```[^\n]*\n.*?```", " ", section_text, flags=re.DOTALL)
    prose = re.sub(r"(?<!`)`[^`\n]+`(?!`)", " ", prose)
    return code, prose


def _token_in(text: str, token: str) -> bool:
    return re.search(rf"(?<![\w]){re.escape(token)}(?![\w])", text) is not None


def _proposal_links_for_section(
    section_text: str,
    inventory: dict[str, dict[str, Any]],
    *,
    include_tests: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Generate conservative deterministic proposals and rejection counters."""
    proposals: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    code, prose = _markdown_evidence(section_text)
    stats = {"excluded_test_units": 0, "generic_matches_rejected": 0, "low_confidence_rejected": 0}
    for unit in sorted(inventory.values(), key=lambda item: (str(item.get("path", "")), str(item.get("source_id", "")))):
        if _source_role(unit) == "test" and not include_tests:
            stats["excluded_test_units"] += 1
            continue
        source_path = str(unit.get("path", ""))
        qualname = str(unit.get("qualname", ""))
        source_id = str(unit.get("source_id", ""))
        match_text: str | None = None
        reason: str | None = None
        evidence_kind: str | None = None
        confidence = "medium"
        if source_id and _token_in(code, source_id):
            match_text = source_id
            reason = f"Code contains stable source id `{source_id}`."
            evidence_kind, confidence = "source-id-in-code", "high"
        elif source_path and _token_in(code, source_path):
            match_text = source_path
            reason = f"Code contains exact source path `{source_path}`."
            evidence_kind = "exact-source-reference"
            confidence = "high"
        elif qualname and qualname != source_path and "." in qualname and _token_in(code, qualname):
            match_text = qualname
            reason = f"Code contains exact qualified symbol `{qualname}`."
            evidence_kind = "exact-qualified-symbol"
            confidence = "high"
        elif unit.get("kind") == "class" and qualname and qualname[:1].isupper() and _token_in(code, qualname):
            match_text = qualname
            reason = f"Code contains public class `{qualname}`."
            evidence_kind = "public-class-in-code"
        elif qualname and "." not in qualname and qualname not in GENERIC_PROPOSAL_NAMES and _token_in(code, qualname):
            module_context = source_path and (_token_in(code, source_path) or _token_in(section_text, source_path))
            if module_context:
                match_text = qualname
                reason = f"Code contains public symbol `{qualname}` with source path context `{source_path}`."
                evidence_kind = "public-symbol-with-path-context"
            else:
                stats["low_confidence_rejected"] += 1
        elif qualname in GENERIC_PROPOSAL_NAMES and _token_in(prose, qualname):
            stats["generic_matches_rejected"] += 1
        if match_text is None:
            continue
        key = (source_id, "implementation-note", "unknown")
        if key in seen:
            continue
        seen.add(key)
        proposals.append(
            {
                "source_unit": source_id,
                "coverage": "implementation-note",
                "impact": "unknown",
                "reason": reason,
                "confidence": confidence,
                "evidence": {"kind": evidence_kind, "text": match_text, "source_role": _source_role(unit)},
            }
        )
    return proposals, stats


def propose_mappings(
    workspace: Workspace,
    *,
    all_docs: bool,
    out_dir: str | None,
    include_tests: bool = False,
    replace_owned_proposals: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Generate deterministic, scan-bound proposals and an ownership manifest."""
    if not all_docs:
        raise DocumentledgerError("invalid_selector", "Use --all-docs for proposal generation.")
    scan = require_current_scan(workspace)
    docs = collect_files(workspace, workspace.config.doc_roots, workspace.config.doc_extensions)
    inventory = current_source_inventory(workspace)
    artifacts_dir = getattr(getattr(workspace, "paths", None), "artifacts_dir", None)
    output_dir = (
        Path(out_dir) if out_dir else ((artifacts_dir / "proposals") if artifacts_dir else workspace.config.storage_dir / "proposals")
    )
    if (
        out_dir is None
        and artifacts_dir is not None
        and workspace.paths is not None
        and getattr(workspace.paths, "layout_source", "legacy") == "canonical"
        and not artifacts_dir.exists()
    ):
        import ledgercore

        from documentledger.project import resolve_canonical_project

        canonical = resolve_canonical_project(workspace.paths.project_root, require_data=True)
        try:
            ledgercore.initialize_storage_binding(cast(Any, canonical.layout).mounts["artifacts"], require_empty=True)
        except (OSError, AtomicWriteError) as exc:
            raise_output_write_error(
                output_dir / PROPOSAL_MANIFEST_NAME,
                command="link propose",
                cause=exc,
                managed_artifact=True,
            )

    manifest_path = output_dir / PROPOSAL_MANIFEST_NAME
    owned_names = existing_owned_filenames(output_dir)
    has_manifest = manifest_path.exists() or manifest_path.is_symlink()
    if has_manifest and not replace_owned_proposals:
        raise DocumentledgerError(
            "proposal_manifest_exists",
            f"A proposal batch already exists in {output_dir}.",
            ["Use --replace-owned-proposals to replace files owned by its manifest, or choose a new --out-dir."],
        )

    targets = {doc_path: output_dir / proposal_filename(doc_path) for doc_path in docs}
    targets_by_name: dict[str, str] = {}
    for doc_path, target in targets.items():
        previous = targets_by_name.get(target.name)
        if previous is not None and previous != doc_path:
            raise DocumentledgerError(
                "proposal_filename_collision",
                f"Different documents resolve to the same proposal target: {previous} and {doc_path}.",
                ["Choose a different output directory and report the collision; no proposal files were written."],
                details={"filename": target.name, "documents": sorted([previous, doc_path])},
            )
        targets_by_name[target.name] = doc_path
        if target.is_symlink():
            raise DocumentledgerError(
                "proposal_output_conflict",
                f"Proposal output is a symlink and will not be replaced: {target}.",
                ["Choose a different proposal output directory."],
            )
        if target.exists() and target.name not in owned_names:
            raise DocumentledgerError(
                "proposal_output_conflict",
                f"Proposal output would overwrite a file not owned by this manifest: {target}.",
                ["Choose a different proposal output directory; unowned files are never overwritten."],
            )

    previous_yaml_names = {path.name for path in output_dir.glob("*.yaml")} if output_dir.exists() else set()
    unowned_before = previous_yaml_names - owned_names - {PROPOSAL_MANIFEST_NAME}
    scan_source_hashes = {str(path): str(value) for path, value in dict(scan.get("source_hashes", {})).items()}
    scan_doc_hashes = {str(path): str(value) for path, value in dict(scan.get("doc_hashes", {})).items()}
    proposal_payloads: list[tuple[str, Path, dict[str, Any], list[dict[str, Any]], dict[str, str]]] = []
    proposed_sections = 0
    proposed_edges = 0
    rejected = {"excluded_test_units": 0, "generic_matches_rejected": 0, "low_confidence_rejected": 0}
    documents_without_candidates: list[str] = []
    events: list[dict[str, Any]] = []

    for doc_path in docs:
        sections_payload: list[dict[str, Any]] = []
        linked_source_paths: set[str] = set()
        for section in doc_sections_for_file(workspace.config.root / doc_path, doc_path):
            links, stats = _proposal_links_for_section(section.text, inventory, include_tests=include_tests)
            for key, value in stats.items():
                rejected[key] += value
            if not links:
                continue
            for link in links:
                unit = inventory.get(str(link["source_unit"]), {})
                source_path = str(unit.get("path", ""))
                if source_path:
                    linked_source_paths.add(source_path)
            sections_payload.append({"section": section.heading_slug, "links": links})
            proposed_sections += 1
            proposed_edges += len(links)
        if not sections_payload:
            documents_without_candidates.append(doc_path)
        proposal_payload = {
            "schema": "documentledger.mapping_proposal.v1",
            "doc_path": doc_path,
            "sections": sections_payload,
        }
        missing_source_hashes = sorted(linked_source_paths - set(scan_source_hashes))
        if missing_source_hashes:
            raise DocumentledgerError(
                "proposal_scan_stale",
                "A proposed source path is missing from the latest scan snapshot.",
                ["Run `documentledger scan` before generating mapping proposals."],
                details={"source_paths": missing_source_hashes},
            )
        source_hashes = {path: scan_source_hashes[path] for path in sorted(linked_source_paths)}
        proposal_payloads.append((doc_path, targets[doc_path], proposal_payload, sections_payload, source_hashes))

    if set(docs) != (set(docs) & set(scan_doc_hashes)):
        raise DocumentledgerError(
            "proposal_scan_stale",
            "The current documentation inventory does not match the latest scan.",
            ["Run `documentledger scan` before generating mapping proposals."],
        )

    for _, target, proposal_payload, sections_payload, _ in proposal_payloads:
        write_output_file(
            target,
            lambda path, payload=proposal_payload: core_write_yaml(path, payload, sort_keys=False),
            command="link propose",
            managed_artifact=out_dir is None,
        )
        events.append({"event": "proposal_written", "file": str(target), "sections": len(sections_payload)})

    manifest_documents: list[dict[str, Any]] = []
    written_files: list[str] = []
    for doc_path, target, _, sections_payload, source_hashes in proposal_payloads:
        outcome = "proposed" if sections_payload else "no_candidates"
        manifest_documents.append(
            {
                "doc_path": doc_path,
                "doc_hash": scan_doc_hashes[doc_path],
                "source_hashes": source_hashes,
                "filename": target.name,
                "proposal_hash": file_hash(target),
                "reviewed": False,
                "reviewed_hash": "",
                "outcome": outcome,
            }
        )
        written_files.append(str(target))
    manifest = {
        "schema": PROPOSAL_MANIFEST_SCHEMA,
        "scan_version": int(scan.get("version", 0)),
        "source_index_hash": str(scan.get("source_index_hash") or ""),
        "source_hashes": scan_source_hashes,
        "doc_hashes": scan_doc_hashes,
        "documents": manifest_documents,
    }
    write_output_file(
        manifest_path,
        lambda path: core_write_yaml(path, manifest, sort_keys=False),
        command="link propose",
        managed_artifact=out_dir is None,
    )
    events.append({"event": "proposal_manifest_written", "file": str(manifest_path), "documents": len(manifest_documents)})
    preserved_unowned = sorted(unowned_before | (owned_names - set(targets_by_name)))
    return (
        {
            "documents": len(docs),
            "documents_considered": len(docs),
            "documents_proposed": len(docs) - len(documents_without_candidates),
            "documents_without_candidates": documents_without_candidates,
            "proposal_files": written_files,
            "proposal_files_written": len(written_files),
            "proposed_sections": proposed_sections,
            "proposed_edges": proposed_edges,
            "rejected_candidates": rejected,
            "collisions": 0,
            "conflicts": 0,
            "review_required": bool(docs),
            "manifest": str(manifest_path),
            "unowned_files_preserved": preserved_unowned,
            "unowned_file_count": len(preserved_unowned),
        },
        events,
    )


def current_doc_sections(workspace: Workspace, doc_path: str) -> list[dict[str, Any]]:
    target = workspace.config.root / doc_path
    sections = doc_sections_for_file(target, doc_path)
    return [section.to_record() for section in sections]


def ensure_valid_enum(value: str, valid_values: set[str], field: str) -> str:
    if value not in valid_values:
        raise DocumentledgerError("invalid_enum", f"Invalid {field}: {value}")
    return value


def section_lookup(workspace: Workspace, doc_path: str) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for section in current_doc_sections(workspace, doc_path):
        lookup[str(section["section_id"])] = dict(section)
        lookup.setdefault(str(section["heading_slug"]), dict(section))
    return lookup


def find_section(workspace: Workspace, doc_path: str, section_ref: str) -> dict[str, Any]:
    lookup = section_lookup(workspace, doc_path)
    if section_ref not in lookup:
        raise DocumentledgerError("section_not_found", f"No section {section_ref} exists in {doc_path}")
    return dict(lookup[section_ref])


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


def source_unit_record(workspace: Workspace, source_unit: str, inventory: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    active_inventory = inventory or current_source_inventory(workspace)
    if source_unit not in active_inventory:
        raise DocumentledgerError("source_unit_not_found", f"Unknown source unit: {source_unit}")
    return dict(active_inventory[source_unit])


def edge_tracked_hashes(unit: dict[str, Any], coverage: str, tracked_hash_names: list[str] | None = None) -> dict[str, str]:
    names = tracked_hash_names or TRACKED_HASH_DEFAULTS.get(coverage, ["file_hash"])
    hashes = dict(unit.get("hashes", {}))
    return {name: str(hashes[name]) for name in names if name in hashes}


def edge_key(edge: dict[str, Any]) -> tuple[str, str, str]:
    return (str(edge.get("source_id", "")), str(edge.get("coverage", "")), str(edge.get("impact", "")))


def add_edge(section: dict[str, Any], edge: dict[str, Any], replace: bool = False) -> bool:
    links = [] if replace else list(section.get("links", []) or [])
    existing_keys = {edge_key(dict(item)) for item in links}
    if edge_key(edge) in existing_keys:
        return False
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
    try:
        section_meta = find_section(workspace, doc_path, section_ref)
    except DocumentledgerError as exc:
        if exc.code != "section_not_found":
            raise
        section_meta = next(
            (
                dict(section)
                for section in (record.get("sections", []) or [])
                if section_ref
                in {
                    str(section.get("section_id", "")),
                    str(section.get("heading_slug", "")),
                }
            ),
            None,
        )
        if section_meta is None:
            raise
    before = str(record)
    target_id = str(section_meta.get("section_id", ""))
    for section in record.get("sections", []) or []:
        if str(section.get("section_id")) != target_id:
            continue
        section["links"] = [link for link in (section.get("links", []) or []) if str(link.get("source_id")) != source_unit]
    live_ids = {str(section["section_id"]) for section in current_doc_sections(workspace, doc_path)}
    record["sections"] = [
        section
        for section in (record.get("sections", []) or [])
        if str(section.get("section_id")) in live_ids or section.get("links", []) or str(section.get("section_id")) != target_id
    ]
    refresh_linked_sources(record)
    if str(record) != before:
        save_doc_record(workspace, record)
        saved = load_doc_record(workspace, doc_path)
        return saved or record
    return record


def load_mapping_payload(path: Path) -> dict[str, Any]:
    payload = read_yaml(path)
    if str(payload.get("schema") or "") != "documentledger.mapping_proposal.v1":
        raise DocumentledgerError("invalid_mapping", f"Unsupported mapping schema in {path}.")
    return payload


def prepare_mapping_batch(workspace: Workspace, mapping_paths: list[Path]) -> PreparedMappingBatch:
    if not mapping_paths:
        raise DocumentledgerError("invalid_mapping", "No mapping files were provided.")
    inventory = current_source_inventory(workspace)
    documents: dict[str, PreparedDocument] = {}
    planned_edges = 0
    empty_mapping_paths: list[str] = []
    for mapping_path in sorted(mapping_paths, key=lambda path: path.as_posix()):
        payload = load_mapping_payload(mapping_path)
        doc_path = validate_existing(workspace, str(payload.get("doc_path", "")), workspace.config.doc_extensions, "doc")
        sections = list(payload.get("sections", []) or [])
        if not sections:
            empty_mapping_paths.append(mapping_path.as_posix())
            continue
        prepared_doc = documents.get(doc_path)
        if prepared_doc is None:
            prepared_doc = PreparedDocument(doc_path=doc_path, record=record_for_doc(workspace, doc_path))
            documents[doc_path] = prepared_doc
            lookup = section_lookup(workspace, doc_path)
        else:
            lookup = section_lookup(workspace, doc_path)
        for section in sections:
            section_ref = str(section.get("section") or section.get("section_id") or "")
            if not section_ref:
                raise DocumentledgerError("invalid_mapping", f"Section entry is missing `section` in {mapping_path}.")
            if section_ref not in lookup:
                raise DocumentledgerError("section_not_found", f"No section {section_ref} exists in {doc_path}")
            section_meta = dict(lookup[section_ref])
            section_id = str(section_meta["section_id"])
            links = list(section.get("links", []) or [])
            if not links:
                raise DocumentledgerError("invalid_mapping", f"Section {section_ref} contains no links.")
            prepared_section = prepared_doc.sections.setdefault(section_id, PreparedSection(section_meta=section_meta))
            for link in links:
                coverage = ensure_valid_enum(str(link.get("coverage") or ""), VALID_COVERAGE, "coverage")
                impact = ensure_valid_enum(str(link.get("impact") or ""), VALID_IMPACT, "impact")
                source_unit = str(link.get("source_unit") or link.get("source_id") or "")
                if not source_unit:
                    raise DocumentledgerError("invalid_mapping", f"Section {section_ref} is missing a source unit.")
                unit = source_unit_record(workspace, source_unit, inventory)
                tracked_hash_names = list(link.get("tracked_hashes", []) or []) or None
                edge = {
                    "source_id": source_unit,
                    "source_path": str(unit.get("path", "")),
                    "coverage": coverage,
                    "impact": impact,
                    "reason": str(link.get("reason") or ""),
                    "tracked_hashes": edge_tracked_hashes(unit, coverage, tracked_hash_names),
                }
                key = edge_key(edge)
                if key in prepared_section.edge_keys:
                    raise DocumentledgerError(
                        "duplicate_edge",
                        f"Duplicate mapping edge for {doc_path}::{section_id} -> {source_unit}.",
                    )
                prepared_section.edge_keys.add(key)
                prepared_section.edges.append(edge)
                planned_edges += 1
    return PreparedMappingBatch(
        mapping_paths=[path.as_posix() for path in sorted(mapping_paths, key=lambda path: path.as_posix())],
        documents=documents,
        planned_edges=planned_edges,
        empty_mapping_paths=empty_mapping_paths,
    )


def apply_mapping_batch(
    workspace: Workspace,
    prepared: PreparedMappingBatch,
    *,
    replace_sections: bool,
) -> dict[str, Any]:
    changed_records: list[dict[str, Any]] = []
    added_edges = 0
    unchanged_edges = 0
    removed_edges = 0
    for doc_path in sorted(prepared.documents):
        document = prepared.documents[doc_path]
        original = document.record
        record = deepcopy(original)
        for section_id in sorted(document.sections):
            prepared_section = document.sections[section_id]
            section = ensure_section_entry(record, prepared_section.section_meta)
            existing_links = list(section.get("links", []) or [])
            existing_keys = {edge_key(dict(link)) for link in existing_links}
            if replace_sections:
                removed_edges += len(existing_keys - prepared_section.edge_keys)
                unchanged_edges += len(existing_keys & prepared_section.edge_keys)
                added_edges += len(prepared_section.edge_keys - existing_keys)
                section["links"] = sorted(
                    [dict(edge) for edge in prepared_section.edges],
                    key=lambda item: (str(item["source_path"]), str(item["source_id"]), str(item["coverage"])),
                )
            else:
                for edge in prepared_section.edges:
                    if edge_key(edge) in existing_keys:
                        unchanged_edges += 1
                        continue
                    existing_links.append(dict(edge))
                    existing_keys.add(edge_key(edge))
                    added_edges += 1
                section["links"] = sorted(
                    existing_links,
                    key=lambda item: (str(item["source_path"]), str(item["source_id"]), str(item["coverage"])),
                )
        refresh_linked_sources(record)
        if record != original:
            changed_records.append(record)
    current_state_version = save_doc_records_batch(workspace, changed_records) if changed_records else state_version(workspace)
    return {
        "mapping_files": len(prepared.mapping_paths),
        "empty_mapping_files": prepared.empty_mapping_count,
        "documents": len(prepared.documents),
        "sections": prepared.section_count,
        "planned_edges": prepared.planned_edges,
        "added_edges": added_edges,
        "unchanged_edges": unchanged_edges,
        "removed_edges": removed_edges,
        "changed_documents": len(changed_records),
        "state_version": current_state_version,
    }


def import_mapping(workspace: Workspace, file_path: str, apply_changes: bool, replace_section: bool = False) -> dict[str, Any]:
    prepared = prepare_mapping_batch(workspace, [Path(file_path)])
    result = (
        apply_mapping_batch(workspace, prepared, replace_sections=replace_section)
        if apply_changes
        else {
            "mapping_files": len(prepared.mapping_paths),
            "empty_mapping_files": prepared.empty_mapping_count,
            "documents": len(prepared.documents),
            "sections": prepared.section_count,
            "planned_edges": prepared.planned_edges,
            "changed_documents": 0,
            "state_version": state_version(workspace),
        }
    )
    return result | {"applied": apply_changes}


def audit_links(workspace: Workspace) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
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
            links = list(section.get("links", []) or [])
            if section_id not in sections and not section_id.endswith("::whole-doc") and links:
                issues.append(
                    {
                        "code": "missing_section",
                        "doc_path": doc_path,
                        "section_id": section_id,
                        "linked_edges": len(links),
                        "message": f"Linked section no longer exists: {section_id}",
                        "remediation": [
                            "Move the links to a current section with `documentledger link add-section`.",
                            "Remove obsolete links with `documentledger link remove-section`.",
                        ],
                    }
                )
            seen_edges: set[tuple[str, str, str]] = set()
            for link in links:
                source_id = str(link.get("source_id", ""))
                key = edge_key(dict(link))
                if key in seen_edges:
                    issues.append({"code": "duplicate_edge", "message": f"Duplicate edge: {section_id} -> {source_id}"})
                seen_edges.add(key)
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
