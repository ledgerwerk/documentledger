from __future__ import annotations

import functools
import json
import os
from collections.abc import Callable
from os.path import relpath
from pathlib import Path
from time import perf_counter
from typing import Any

import typer
from ledgercore.atomic import atomic_write_text
from ledgercore.yamlio import write_yaml as core_write_yaml

from documentledger.doc_index import doc_sections_for_file
from documentledger.errors import DocumentledgerError
from documentledger.identity import normalize_repo_path
from documentledger.impact import resolve_affected_sections
from documentledger.links import (
    add_link,
    add_section_link,
    apply_mapping_batch,
    audit_links,
    current_source_inventory,
    list_links,
    prepare_mapping_batch,
    remove_link,
    remove_section_link,
)
from documentledger.render import render_context, stale_details
from documentledger.scanner import collect_files, file_hash, run_scan
from documentledger.storage import (
    STORAGE_SCHEMA_VERSION,
    coerce_int,
    iter_doc_records,
    latest_scan,
    load_doc_record,
    load_workspace,
    save_doc_record,
)

app = typer.Typer(no_args_is_help=True)
links_app = typer.Typer(no_args_is_help=True)
docs_app = typer.Typer(no_args_is_help=True)
sources_app = typer.Typer(no_args_is_help=True)
app.add_typer(links_app, name="links")
app.add_typer(docs_app, name="docs")
app.add_typer(sources_app, name="sources")


def envelope(command: str, result: Any = None, events: list[Any] | None = None) -> dict[str, Any]:
    return {"ok": True, "command": command, "result": result or {}, "events": events or []}


def error_envelope(command: str, error: DocumentledgerError) -> dict[str, Any]:
    return {
        "ok": False,
        "command": command,
        "error": {"code": error.code, "message": error.message, "remediation": error.remediation},
        "events": [],
    }


def emit(ctx: typer.Context, command: str, result: Any, human: str, events: list[Any] | None = None) -> None:
    if ctx.obj.get("json"):
        typer.echo(json.dumps(envelope(command, result, events), sort_keys=True))
    else:
        typer.echo(human)


def render_error(ctx: typer.Context, command: str, exc: DocumentledgerError) -> None:
    if ctx.obj.get("json"):
        typer.echo(json.dumps(error_envelope(command, exc), sort_keys=True))
    else:
        lines = [f"Error: {exc.message}"]
        for hint in exc.remediation:
            lines.append(f"  hint: {hint}")
        typer.echo("\n".join(lines), err=True)


def handle_errors(command: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapper(ctx: typer.Context, *args: Any, **kwargs: Any) -> Any:
            try:
                return func(ctx, *args, **kwargs)
            except DocumentledgerError as exc:
                render_error(ctx, command, exc)
                raise typer.Exit(code=exc.exit_code) from exc

        return wrapper

    return decorator


def display_path(root: Path, path: Path) -> str:
    root_resolved = root.resolve()
    path_resolved = path.resolve()
    try:
        return path_resolved.relative_to(root_resolved).as_posix()
    except ValueError:
        return Path(relpath(path_resolved, root_resolved)).as_posix()


def profile_events(ctx: typer.Context, operation: str, started_at: float) -> list[dict[str, Any]]:
    if not ctx.obj.get("profile"):
        return []
    return [{"event": "profile", "operation": operation, "elapsed_ms": round((perf_counter() - started_at) * 1000, 3)}]


def scan_diagnostics(workspace: Any) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    source_roots = list(workspace.config.source_roots)
    source_counts: dict[str, int] = {}
    tests_count = 0
    production_count = 0
    for root_text in source_roots:
        path = workspace.config.root / root_text
        if not path.exists():
            issues.append({"code": "missing_source_root", "message": f"Configured source root does not exist: {root_text}"})
            continue
        files = collect_files(workspace, [root_text], workspace.config.source_extensions)
        source_counts[root_text] = len(files)
        if not files:
            issues.append({"code": "empty_source_root", "message": f"No source files were collected from configured root: {root_text}"})
        if root_text.startswith("test"):
            tests_count += len(files)
        else:
            production_count += len(files)
    project_root = workspace.config.project_name.replace("-", "_")
    if (workspace.config.root / project_root).exists() and project_root not in source_roots:
        issues.append(
            {
                "code": "package_root_not_configured",
                "message": f"Configured source roots do not include the project package root: {project_root}",
            }
        )
    if production_count == 0 and tests_count > 0:
        issues.append(
            {
                "code": "tests_without_production_root",
                "message": "Most indexed sources would come from tests while the production package is absent.",
            }
        )
    return issues


def status_classification(workspace: Any) -> tuple[str, str, str]:
    last_scan_version = coerce_int(workspace.metadata.get("last_scan_version"), 0)
    affected_count = coerce_int(workspace.metadata.get("last_scan_affected_section_count"), 0)
    unlinked_changed = coerce_int(workspace.metadata.get("last_scan_unlinked_changed_source_count"), 0)
    linked_sections = sum(
        1 for record in iter_doc_records(workspace) for section in (record.get("sections", []) or []) if section.get("links")
    )
    if last_scan_version <= 0:
        return ("bootstrap_required", "No baseline scan exists yet.", "docledger --json scan")
    if linked_sections <= 0:
        return (
            "bootstrap_required",
            "A baseline scan exists but no documentation links exist.",
            "docledger docs build-context --bootstrap --out .documentledger/rendered/latest-context.md",
        )
    if affected_count > 0:
        return (
            "incremental_affected",
            "Linked documentation sections are affected by the latest source changes.",
            "docledger docs build-context --affected --out .documentledger/rendered/latest-context.md",
        )
    if unlinked_changed > 0:
        return (
            "mapping_incomplete",
            "Changed source files are not fully linked to documentation.",
            "docledger links propose --all-docs --out-dir .documentledger/proposals",
        )
    return ("incremental_clean", "No affected linked sections remain after the latest scan.", "docledger --json scan")


def normalize_cursor(cursor: str | None) -> int:
    if cursor is None:
        return 0
    try:
        value = int(cursor)
    except ValueError as exc:
        raise DocumentledgerError("invalid_cursor", f"Invalid cursor: {cursor}") from exc
    if value < 0:
        raise DocumentledgerError("invalid_cursor", f"Invalid cursor: {cursor}")
    return value


def trim_source_record(unit: dict[str, Any], *, include_hashes: bool) -> dict[str, Any]:
    trimmed = dict(unit)
    if not include_hashes:
        trimmed.pop("hashes", None)
    return trimmed


def coverage_result(workspace: Any) -> dict[str, Any]:
    docs = collect_files(workspace, workspace.config.doc_roots, workspace.config.doc_extensions)
    sections_total = 0
    sections_linked = 0
    for doc_path in docs:
        sections_total += len(doc_sections_for_file(workspace.config.root / doc_path, doc_path))
    linked_sources: set[str] = set()
    linked_source_ids: set[str] = set()
    doc_paths_with_records: set[str] = set()
    for record in iter_doc_records(workspace):
        doc_path = str(record.get("doc_path", ""))
        doc_paths_with_records.add(doc_path)
        for section in record.get("sections", []) or []:
            if list(section.get("links", []) or []):
                sections_linked += 1
            for link in section.get("links", []) or []:
                linked_sources.add(str(link.get("source_path", "")))
                linked_source_ids.add(str(link.get("source_id", "")))
    inventory = current_source_inventory(workspace)
    return {
        "documents": {
            "total": len(docs),
            "with_records": len(doc_paths_with_records),
            "without_records": max(len(docs) - len(doc_paths_with_records), 0),
        },
        "sections": {"total": sections_total, "linked": sections_linked, "unlinked": max(sections_total - sections_linked, 0)},
        "sources": {
            "files": len({str(unit.get("path", "")) for unit in inventory.values()}),
            "files_linked": len({path for path in linked_sources if path}),
            "files_unlinked": max(
                len({str(unit.get("path", "")) for unit in inventory.values()}) - len({path for path in linked_sources if path}), 0
            ),
            "units": len(inventory),
            "units_linked": len({source_id for source_id in linked_source_ids if source_id}),
        },
        "issues": [],
    }


def proposal_links_for_text(section_text: str, inventory: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    proposals: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for unit in sorted(inventory.values(), key=lambda item: (str(item.get("path", "")), str(item.get("source_id", "")))):
        source_path = str(unit.get("path", ""))
        qualname = str(unit.get("qualname", ""))
        match_text = None
        reason = None
        evidence_kind = None
        if source_path and source_path in section_text:
            match_text = source_path
            reason = f"Section contains exact source path `{source_path}`."
            evidence_kind = "exact-source-reference"
        elif qualname and qualname != source_path and qualname in section_text:
            match_text = qualname
            reason = f"Section contains exact qualified symbol `{qualname}`."
            evidence_kind = "exact-qualified-symbol"
        if match_text is None:
            continue
        source_id = str(unit.get("source_id", ""))
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
                "confidence": "high",
                "evidence": {"kind": evidence_kind, "text": match_text},
            }
        )
    return proposals


@app.callback()
def main(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", help="Emit JSON envelope."),
    profile: bool = typer.Option(False, "--profile", help="Emit lightweight profiling metadata."),
) -> None:
    ctx.obj = {"json": json_output, "profile": profile or os.getenv("DOCLEDGER_PROFILE") == "1"}


@app.command()
@handle_errors("init")
def init(
    ctx: typer.Context,
    project_name: str | None = typer.Option(None, "--project-name"),
    documentledger_dir: str = typer.Option(".documentledger", "--documentledger-dir"),
    hidden_config: bool = typer.Option(False, "--hidden-config"),
) -> None:
    from documentledger.storage import init_workspace

    workspace = init_workspace(project_name, documentledger_dir, hidden_config)
    result = status_result(workspace)
    emit(ctx, "init", result, f"Initialized Documentledger for {workspace.config.project_name}")


def status_result(workspace: Any | None) -> dict[str, Any]:
    if workspace is None:
        return {
            "initialized": False,
            "state": "uninitialized",
            "storage_present": False,
            "config_path": None,
            "storage_dir": None,
            "project_name": None,
            "project_uuid": None,
            "last_scan_version": None,
            "recommended_command": "docledger init",
            "recommended_reason": "No Documentledger workspace exists yet.",
            "remediation": ["Run `docledger init` from the project root."],
        }
    config_rel = display_path(workspace.config.root, workspace.config.path)
    storage_rel = display_path(workspace.config.root, workspace.config.storage_dir)
    storage_present = (workspace.config.storage_dir / "storage.yaml").exists()
    if not storage_present:
        return {
            "initialized": False,
            "state": "uninitialized",
            "storage_present": False,
            "config_path": config_rel,
            "storage_dir": storage_rel,
            "project_name": workspace.config.project_name,
            "project_uuid": workspace.config.project_uuid,
            "last_scan_version": None,
            "recommended_command": "docledger init",
            "recommended_reason": "The config exists but storage metadata is missing.",
            "remediation": ["Run `docledger init` from the project root to create storage metadata."],
        }
    issues = scan_diagnostics(workspace)
    state, reason, command = status_classification(workspace)
    return {
        "initialized": True,
        "state": state,
        "storage_present": True,
        "config_path": config_rel,
        "storage_dir": storage_rel,
        "project_name": workspace.config.project_name,
        "project_uuid": workspace.metadata.get("project_uuid") or workspace.config.project_uuid,
        "last_scan_version": coerce_int(workspace.metadata.get("last_scan_version"), 0) or None,
        "last_scan_source_file_count": coerce_int(workspace.metadata.get("last_scan_source_file_count"), 0),
        "last_scan_source_unit_count": coerce_int(workspace.metadata.get("last_scan_source_unit_count"), 0),
        "last_scan_doc_file_count": coerce_int(workspace.metadata.get("last_scan_doc_file_count"), 0),
        "last_scan_affected_section_count": coerce_int(workspace.metadata.get("last_scan_affected_section_count"), 0),
        "last_scan_unlinked_changed_source_count": coerce_int(workspace.metadata.get("last_scan_unlinked_changed_source_count"), 0),
        "recommended_command": command,
        "recommended_reason": reason,
        "issues": issues,
    }


@app.command()
@handle_errors("status")
def status(ctx: typer.Context) -> None:
    started_at = perf_counter()
    workspace = load_workspace(required=False)
    result = status_result(workspace)
    human = "Documentledger initialized." if result["initialized"] else "Documentledger is not initialized."
    emit(ctx, "status", result, human, profile_events(ctx, "status", started_at))


@app.command()
@handle_errors("doctor")
def doctor(ctx: typer.Context) -> None:
    started_at = perf_counter()
    workspace = load_workspace()
    issues: list[dict[str, str]] = list(scan_diagnostics(workspace))
    if workspace.metadata.get("schema_version") != STORAGE_SCHEMA_VERSION:
        issues.append({"code": "schema_mismatch", "message": f"storage.yaml schema_version is not {STORAGE_SCHEMA_VERSION}"})
    for record in iter_doc_records(workspace):
        doc_path = str(record.get("doc_path", ""))
        try:
            normalize_repo_path(doc_path)
        except DocumentledgerError as exc:
            issues.append({"code": exc.code, "message": exc.message})
        if not (workspace.config.root / doc_path).exists():
            issues.append({"code": "missing_doc", "message": f"Missing doc file: {doc_path}"})
    if coerce_int(workspace.metadata.get("last_scan_version"), 0) > 0 and latest_scan(workspace) is None:
        issues.append({"code": "scan_missing", "message": "storage metadata references a latest scan, but scan.yaml is missing."})
    audit = audit_links(workspace)
    issues.extend(list(audit.get("issues", [])))
    result = {"ok": not issues, "issues": issues}
    emit(ctx, "doctor", result, "Doctor passed." if not issues else "Doctor found issues.", profile_events(ctx, "doctor", started_at))


@app.command()
@handle_errors("scan")
def scan(ctx: typer.Context) -> None:
    started_at = perf_counter()
    result_obj = run_scan(load_workspace())
    result = {
        "version": result_obj.version,
        "unchanged": result_obj.unchanged,
        "changed_sources": result_obj.changed_sources,
        "deleted_sources": result_obj.deleted_sources,
        "changed_units": result_obj.changed_units,
        "added_units": result_obj.added_units,
        "deleted_units": result_obj.deleted_units,
        "affected_sections": result_obj.affected_sections,
        "stale_docs": result_obj.stale_docs,
        "unlinked_changed_sources": result_obj.unlinked_changed_sources,
        "unmapped_changed_units": result_obj.unmapped_changed_units,
    }
    human = (
        f"No tracked file changes since scan version {result_obj.version}"
        if result_obj.unchanged
        else f"Recorded scan version {result_obj.version}"
    )
    emit(ctx, "scan", result, human, profile_events(ctx, "scan", started_at))


@app.command("coverage")
@handle_errors("coverage")
def coverage(ctx: typer.Context) -> None:
    started_at = perf_counter()
    workspace = load_workspace()
    result = coverage_result(workspace)
    emit(ctx, "coverage", result, "Coverage computed.", profile_events(ctx, "coverage", started_at))


_SOURCES_LIST_KIND = typer.Option(None, "--kind")


@sources_app.command("list")
@handle_errors("sources list")
def sources_list(
    ctx: typer.Context,
    kind: list[str] = _SOURCES_LIST_KIND,
    path: str | None = typer.Option(None, "--path"),
    path_prefix: str | None = typer.Option(None, "--path-prefix"),
    qualname: str | None = typer.Option(None, "--qualname"),
    query: str | None = typer.Option(None, "--query"),
    ids_only: bool = typer.Option(False, "--ids-only"),
    include_hashes: bool = typer.Option(False, "--include-hashes"),
    limit: int = typer.Option(100, "--limit"),
    cursor: str | None = typer.Option(None, "--cursor"),
) -> None:
    started_at = perf_counter()
    kind = kind or []
    workspace = load_workspace()
    inventory = current_source_inventory(workspace)
    selected = sorted(inventory.values(), key=lambda item: str(item.get("source_id", "")))
    if kind:
        allowed = {value.strip() for value in kind}
        selected = [unit for unit in selected if str(unit.get("kind", "")) in allowed]
    if path is not None:
        wanted_path = normalize_repo_path(path)
        selected = [unit for unit in selected if str(unit.get("path", "")) == wanted_path]
    if path_prefix is not None:
        normalized_prefix = normalize_repo_path(path_prefix)
        selected = [unit for unit in selected if str(unit.get("path", "")).startswith(normalized_prefix)]
    if qualname is not None:
        selected = [unit for unit in selected if str(unit.get("qualname", "")) == qualname]
    if query is not None:
        lowered = query.lower()
        selected = [
            unit
            for unit in selected
            if lowered in str(unit.get("source_id", "")).lower()
            or lowered in str(unit.get("path", "")).lower()
            or lowered in str(unit.get("qualname", "")).lower()
        ]
    offset = normalize_cursor(cursor)
    page = selected[offset : offset + max(limit, 0)]
    next_cursor = offset + len(page) if offset + len(page) < len(selected) else None
    result_sources = (
        [str(item.get("source_id", "")) for item in page]
        if ids_only
        else [trim_source_record(dict(item), include_hashes=include_hashes) for item in page]
    )
    result = {"sources": result_sources, "count": len(page), "total": len(selected), "next_cursor": next_cursor}
    human = "\n".join(str(item["source_id"]) for item in page) or "No source units."
    emit(ctx, "sources list", result, human, profile_events(ctx, "sources list", started_at))


@sources_app.command("show")
@handle_errors("sources show")
def sources_show(ctx: typer.Context, source_id: str = typer.Argument(...)) -> None:
    inventory = current_source_inventory(load_workspace())
    if source_id not in inventory:
        raise DocumentledgerError("source_unit_not_found", f"Unknown source unit: {source_id}")
    emit(ctx, "sources show", inventory[source_id], source_id)


@links_app.command("list")
@handle_errors("links list")
def links_list(ctx: typer.Context) -> None:
    records = list_links(load_workspace())
    emit(ctx, "links list", {"docs": records}, "\n".join(str(r["doc_path"]) for r in records) or "No links.")


@links_app.command("add")
@handle_errors("links add")
def links_add(
    ctx: typer.Context,
    doc: str = typer.Option(..., "--doc"),
    source: str = typer.Option(..., "--source"),
    reason: str | None = typer.Option(None, "--reason"),
) -> None:
    record = add_link(load_workspace(), doc, source, reason)
    emit(ctx, "links add", record, f"Linked {source} to {doc}")


@links_app.command("remove")
@handle_errors("links remove")
def links_remove(ctx: typer.Context, doc: str = typer.Option(..., "--doc"), source: str = typer.Option(..., "--source")) -> None:
    record = remove_link(load_workspace(), doc, source)
    emit(ctx, "links remove", record, f"Removed {source} from {doc}")


@links_app.command("add-section")
@handle_errors("links add-section")
def links_add_section(
    ctx: typer.Context,
    doc: str = typer.Option(..., "--doc"),
    section: str = typer.Option(..., "--section"),
    source_unit: str = typer.Option(..., "--source-unit"),
    coverage: str = typer.Option(..., "--coverage"),
    impact: str = typer.Option(..., "--impact"),
    reason: str = typer.Option(..., "--reason"),
) -> None:
    record = add_section_link(load_workspace(), doc, section, source_unit, coverage, impact, reason)
    emit(ctx, "links add-section", record, f"Linked {source_unit} to {doc} section {section}")


@links_app.command("remove-section")
@handle_errors("links remove-section")
def links_remove_section(
    ctx: typer.Context,
    doc: str = typer.Option(..., "--doc"),
    section: str = typer.Option(..., "--section"),
    source_unit: str = typer.Option(..., "--source-unit"),
) -> None:
    record = remove_section_link(load_workspace(), doc, section, source_unit)
    emit(ctx, "links remove-section", record, f"Removed {source_unit} from {doc} section {section}")


_LINKS_IMPORT_MAP_FILE = typer.Option(None, "--file")


@links_app.command("import-map")
@handle_errors("links import-map")
def links_import_map(
    ctx: typer.Context,
    file_path: list[str] = _LINKS_IMPORT_MAP_FILE,
    directory: str | None = typer.Option(None, "--directory"),
    validate: bool = typer.Option(False, "--validate"),
    apply: bool = typer.Option(False, "--apply"),
    check_and_apply: bool = typer.Option(False, "--check-and-apply"),
    replace_section: bool = typer.Option(False, "--replace-section"),
) -> None:
    started_at = perf_counter()
    file_path = file_path or []
    mode_count = sum(bool(value) for value in (validate, apply, check_and_apply))
    if mode_count != 1:
        raise DocumentledgerError("invalid_selector", "Choose exactly one of --validate, --apply, or --check-and-apply.")
    mapping_paths = [Path(path) for path in file_path]
    if directory is not None:
        mapping_paths.extend(sorted(Path(directory).glob("*.yaml")))
    if not mapping_paths:
        raise DocumentledgerError("invalid_mapping", "Provide at least one --file or a --directory.")
    workspace = load_workspace()
    prepared = prepare_mapping_batch(workspace, mapping_paths)
    events = [{"event": "mapping_validated", "file": path} for path in prepared.mapping_paths]
    if validate:
        result = {
            "mapping_files": len(prepared.mapping_paths),
            "documents": len(prepared.documents),
            "sections": prepared.section_count,
            "planned_edges": prepared.planned_edges,
            "applied": False,
        }
        emit(ctx, "links import-map", result, "Mapping validated.", events + profile_events(ctx, "links import-map", started_at))
        return
    result = apply_mapping_batch(workspace, prepared, replace_sections=replace_section) | {"applied": True}
    for doc_path in sorted(prepared.documents):
        events.append({"event": "document_saved", "doc": doc_path})
    emit(
        ctx,
        "links import-map",
        result,
        "Mapping applied." if apply else "Mapping validated and applied.",
        events + profile_events(ctx, "links import-map", started_at),
    )


@links_app.command("audit")
@handle_errors("links audit")
def links_audit(ctx: typer.Context) -> None:
    result = audit_links(load_workspace())
    emit(ctx, "links audit", result, "Link audit passed." if result["ok"] else "Link audit found issues.")


@links_app.command("propose")
@handle_errors("links propose")
def links_propose(
    ctx: typer.Context,
    all_docs: bool = typer.Option(False, "--all-docs"),
    out_dir: str = typer.Option(..., "--out-dir"),
) -> None:
    started_at = perf_counter()
    if not all_docs:
        raise DocumentledgerError("invalid_selector", "Use --all-docs for proposal generation.")
    workspace = load_workspace()
    inventory = current_source_inventory(workspace)
    docs = collect_files(workspace, workspace.config.doc_roots, workspace.config.doc_extensions)
    output_dir = Path(out_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    written_files: list[str] = []
    proposed_sections = 0
    proposed_edges = 0
    events: list[dict[str, Any]] = []
    for doc_path in docs:
        sections_payload: list[dict[str, Any]] = []
        for section in doc_sections_for_file(workspace.config.root / doc_path, doc_path):
            links = proposal_links_for_text(section.text, inventory)
            if not links:
                continue
            sections_payload.append({"section": section.heading_slug, "links": links})
            proposed_sections += 1
            proposed_edges += len(links)
        if not sections_payload:
            continue
        target = output_dir / f"{Path(doc_path).stem}.yaml"
        core_write_yaml(
            target,
            {"schema": "documentledger.mapping_proposal.v1", "doc_path": doc_path, "sections": sections_payload},
            sort_keys=False,
        )
        written_files.append(str(target))
        events.append({"event": "proposal_written", "file": str(target), "sections": len(sections_payload)})
    result = {
        "documents": len(docs),
        "proposal_files": written_files,
        "proposed_sections": proposed_sections,
        "proposed_edges": proposed_edges,
    }
    emit(
        ctx,
        "links propose",
        result,
        f"Wrote {len(written_files)} proposal files.",
        events + profile_events(ctx, "links propose", started_at),
    )


@docs_app.command("list")
@handle_errors("docs list")
def docs_list(ctx: typer.Context) -> None:
    started_at = perf_counter()
    workspace = load_workspace()
    docs = collect_files(workspace, workspace.config.doc_roots, workspace.config.doc_extensions)
    emit(ctx, "docs list", {"docs": docs}, "\n".join(docs) or "No docs.", profile_events(ctx, "docs list", started_at))


@docs_app.command("sections")
@handle_errors("docs sections")
def docs_sections(
    ctx: typer.Context,
    doc: str | None = typer.Option(None, "--doc"),
    all_docs: bool = typer.Option(False, "--all"),
    ids_only: bool = typer.Option(False, "--ids-only"),
    outline: bool = typer.Option(False, "--outline"),
) -> None:
    started_at = perf_counter()
    workspace = load_workspace()
    if doc and all_docs:
        raise DocumentledgerError("invalid_selector", "Use --doc or --all, not both.")
    docs_to_read = (
        [normalize_repo_path(doc)]
        if doc
        else collect_files(workspace, workspace.config.doc_roots, workspace.config.doc_extensions)
        if all_docs
        else []
    )
    if not docs_to_read:
        raise DocumentledgerError("doc_required", "Select --doc DOC or --all.")
    result = {
        "docs": [
            {
                "doc_path": doc_path,
                "sections": [
                    (
                        str(section.section_id)
                        if ids_only
                        else {
                            key: value
                            for key, value in section.to_record().items()
                            if key in {"section_id", "doc_path", "heading_path", "heading_slug", "line_span"} or not outline
                        }
                    )
                    for section in doc_sections_for_file(workspace.config.root / doc_path, doc_path)
                ],
            }
            for doc_path in docs_to_read
        ]
    }
    human = "\n".join(doc_path for doc_path in docs_to_read)
    emit(ctx, "docs sections", result, human or "No docs.", profile_events(ctx, "docs sections", started_at))


@docs_app.command("affected")
@handle_errors("docs affected")
def docs_affected(ctx: typer.Context, doc: str | None = typer.Option(None, "--doc")) -> None:
    workspace = load_workspace()
    docs = [normalize_repo_path(doc)] if doc else None
    affected = resolve_affected_sections(workspace, docs=docs)
    human = ["Affected documentation sections:"]
    if not affected:
        human.append("- None")
    for item in affected:
        heading = " / ".join(item["heading_path"]) or item["section_id"]
        human.append(f"- {item['doc_path']} :: {heading}")
    emit(ctx, "docs affected", {"affected_sections": affected}, "\n".join(human))


@docs_app.command("stale")
@handle_errors("docs stale")
def docs_stale(ctx: typer.Context) -> None:
    details = stale_details(load_workspace())
    human = ["Stale documentation:"]
    if not details:
        human.append("- None")
    for item in details:
        human.extend([f"- {item['doc_path']}", "  Affected sections:"])
        for section in item["affected_sections"]:
            heading = " / ".join(section["heading_path"]) or section["section_id"]
            human.append(f"  - {heading}")
        if not item["affected_sections"]:
            human.append("  - None")
        human.append("  Changed sources:")
        human.extend(f"  - {source}" for source in item["changed_sources"])
        if not item["changed_sources"]:
            human.append("  - None")
        human.append("  Deleted sources:")
        human.extend(f"  - {source}" for source in item["deleted_sources"])
        if not item["deleted_sources"]:
            human.append("  - None")
    emit(ctx, "docs stale", {"stale_docs": details}, "\n".join(human))


@docs_app.command("build-context")
@handle_errors("docs build-context")
def docs_build_context(
    ctx: typer.Context,
    doc: str | None = typer.Option(None, "--doc"),
    section: str | None = typer.Option(None, "--section"),
    all_docs: bool = typer.Option(False, "--all"),
    affected: bool = typer.Option(False, "--affected"),
    bootstrap: bool = typer.Option(False, "--bootstrap"),
    include_unlinked: bool = typer.Option(False, "--include-unlinked"),
    out: str | None = typer.Option(None, "--out"),
    print_output: bool = typer.Option(False, "--print"),
    max_source_lines: int = typer.Option(40, "--max-source-lines"),
    max_section_lines: int = typer.Option(80, "--max-section-lines"),
    max_bytes: int = typer.Option(250_000, "--max-bytes"),
) -> None:
    started_at = perf_counter()
    workspace = load_workspace()
    if section and not doc:
        raise DocumentledgerError("doc_required", "Use --doc when selecting --section.")
    selector_count = sum(bool(value) for value in (doc, all_docs, affected, bootstrap))
    if selector_count != 1:
        raise DocumentledgerError("invalid_selector", "Select exactly one primary mode: --affected, --doc, --all, or --bootstrap.")
    selected = [normalize_repo_path(doc)] if doc else None
    mode = "bootstrap" if bootstrap else "affected" if affected else "all" if all_docs else "doc"
    rendered = render_context(
        workspace,
        mode=mode,
        docs=selected,
        section_id=section,
        include_unlinked=include_unlinked,
        max_source_lines=max_source_lines,
        max_section_lines=max_section_lines,
        max_bytes=max_bytes,
    )
    output_path = Path(out) if out else workspace.config.storage_dir / "rendered" / "latest-context.md"
    atomic_write_text(output_path, str(rendered["content"]))
    if print_output and ctx.obj.get("json"):
        typer.echo(rendered["content"])
    result = {key: value for key, value in rendered.items() if key != "content"} | {"path": str(output_path)}
    human = str(rendered["content"]) if print_output else f"Saved context to {output_path}"
    emit(ctx, "docs build-context", result, human, profile_events(ctx, "docs build-context", started_at))


def selected_sections_for_mark_fresh(
    workspace: Any,
    doc_path: str,
    section_ref: str | None,
    allow_unlinked: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    record = load_doc_record(workspace, doc_path) or {
        "schema": "documentledger.doc_record.v4",
        "doc_path": doc_path,
        "linked_sources": [],
        "sections": [section.to_record() | {"links": []} for section in doc_sections_for_file(workspace.config.root / doc_path, doc_path)],
        "last_fresh_scan_version": 0,
        "last_fresh_hash": "",
        "notes": "",
        "version": 0,
    }
    linked = record.get("linked_sources", []) or []
    if not linked and not allow_unlinked:
        raise DocumentledgerError(
            "unlinked_doc",
            f"{doc_path} has no linked sources; mark-fresh is rejected for unlinked docs by default.",
            [
                "Add links with `docledger links add` or `docledger links add-section` before marking this doc fresh.",
                "Pass --allow-unlinked to record this doc as intentionally unlinked.",
            ],
        )
    if section_ref:
        wanted = [
            section
            for section in record.get("sections", []) or []
            if section_ref in {str(section.get("heading_slug")), str(section.get("section_id"))}
        ]
        if not wanted:
            raise DocumentledgerError("section_not_found", f"No section {section_ref} exists in {doc_path}")
        return record, wanted
    affected_sections = resolve_affected_sections(workspace, docs=[doc_path])
    affected_ids = {str(item["section_id"]) for item in affected_sections}
    selected = [section for section in (record.get("sections", []) or []) if str(section.get("section_id")) in affected_ids] or list(
        record.get("sections", []) or []
    )
    return record, selected


@app.command("mark-fresh")
@handle_errors("mark-fresh")
def mark_fresh(
    ctx: typer.Context,
    doc: str | None = typer.Option(None, "--doc"),
    section: str | None = typer.Option(None, "--section"),
    all_docs: bool = typer.Option(False, "--all"),
    allow_unlinked: bool = typer.Option(False, "--allow-unlinked"),
    reason: str = typer.Option(..., "--reason"),
) -> None:
    if not reason.strip():
        raise DocumentledgerError("reason_required", "mark-fresh requires a non-empty reason.")
    workspace = load_workspace()
    scan_record = latest_scan(workspace)
    if scan_record is None:
        raise DocumentledgerError("scan_missing", "mark-fresh requires a latest scan.")
    if doc and all_docs:
        raise DocumentledgerError("invalid_selector", "Use --doc or --all, not both.")
    if section and not doc:
        raise DocumentledgerError("doc_required", "Use --doc when selecting --section.")
    doc_paths = (
        [normalize_repo_path(doc)]
        if doc
        else sorted({str(item["doc_path"]) for item in resolve_affected_sections(workspace)})
        if all_docs
        else []
    )
    if not doc_paths:
        raise DocumentledgerError("doc_required", "Select --doc DOC or --all.")
    inventory = current_source_inventory(workspace)
    updated_docs: list[str] = []
    updated_sections: list[str] = []
    for doc_path in doc_paths:
        record, sections = selected_sections_for_mark_fresh(workspace, doc_path, section, allow_unlinked)
        before = json.dumps(record, sort_keys=True)
        for selected_section in sections:
            for current_section in doc_sections_for_file(workspace.config.root / doc_path, doc_path):
                if current_section.section_id != str(selected_section.get("section_id")):
                    continue
                selected_section["heading_path"] = list(current_section.heading_path)
                selected_section["heading_slug"] = current_section.heading_slug
                selected_section["line_span"] = [current_section.line_span[0], current_section.line_span[1]]
                selected_section["section_hash"] = current_section.section_hash
                selected_section["summary"] = current_section.summary
                break
            for link in selected_section.get("links", []) or []:
                source_id = str(link.get("source_id", ""))
                if source_id not in inventory:
                    raise DocumentledgerError(
                        "source_unit_not_found",
                        f"Cannot mark fresh while linked source unit is missing: {source_id}",
                    )
                current_unit = inventory[source_id]
                tracked = dict(link.get("tracked_hashes", {}))
                link["tracked_hashes"] = {
                    name: str(current_unit["hashes"][name]) for name in tracked if name in current_unit.get("hashes", {})
                }
            updated_sections.append(f"{doc_path}::{selected_section['heading_slug']}")
        record["last_fresh_scan_version"] = scan_record["version"]
        record["last_fresh_hash"] = file_hash(workspace.config.root / doc_path)
        record["notes"] = reason if record.get("linked_sources") else f"{reason} (intentionally unlinked)"
        if json.dumps(record, sort_keys=True) != before:
            save_doc_record(workspace, record)
        updated_docs.append(doc_path)
    emit(
        ctx,
        "mark-fresh",
        {"updated_docs": updated_docs, "updated_sections": updated_sections, "scan_version": scan_record["version"]},
        "Marked docs fresh.",
    )


def run() -> None:
    try:
        app()
    except DocumentledgerError as exc:
        typer.echo(f"Error: {exc.message}", err=True)
        raise typer.Exit(code=exc.exit_code) from exc
