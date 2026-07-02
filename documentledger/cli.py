from __future__ import annotations

import functools
import json
from collections.abc import Callable
from os.path import relpath
from pathlib import Path
from typing import Any

import typer
from ledgercore.atomic import atomic_write_text

from documentledger.doc_index import doc_sections_for_file
from documentledger.errors import DocumentledgerError
from documentledger.identity import normalize_repo_path
from documentledger.impact import resolve_affected_sections
from documentledger.links import (
    add_link,
    add_section_link,
    audit_links,
    current_source_inventory,
    import_mapping,
    list_links,
    remove_link,
    remove_section_link,
)
from documentledger.render import render_context, stale_details
from documentledger.scanner import collect_files, file_hash, run_scan
from documentledger.storage import (
    STORAGE_SCHEMA_VERSION,
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


def emit(ctx: typer.Context, command: str, result: Any, human: str) -> None:
    if ctx.obj.get("json"):
        typer.echo(json.dumps(envelope(command, result), sort_keys=True))
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


@app.callback()
def main(ctx: typer.Context, json_output: bool = typer.Option(False, "--json", help="Emit JSON envelope.")) -> None:
    ctx.obj = {"json": json_output}


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
            "remediation": ["Run `docledger init` from the project root."],
        }
    config_rel = display_path(workspace.config.root, workspace.config.path)
    storage_rel = display_path(workspace.config.root, workspace.config.storage_dir)
    storage_present = (workspace.config.storage_dir / "storage.yaml").exists()
    if not storage_present:
        return {
            "initialized": False,
            "state": "config_only",
            "storage_present": False,
            "config_path": config_rel,
            "storage_dir": storage_rel,
            "project_name": workspace.config.project_name,
            "project_uuid": workspace.config.project_uuid,
            "last_scan_version": None,
            "remediation": ["Run `docledger init` from the project root to create storage metadata."],
        }
    scan = latest_scan(workspace)
    return {
        "initialized": True,
        "state": "initialized",
        "storage_present": True,
        "config_path": config_rel,
        "storage_dir": storage_rel,
        "project_name": workspace.config.project_name,
        "project_uuid": workspace.metadata.get("project_uuid") or workspace.config.project_uuid,
        "last_scan_version": int(scan["version"]) if scan else None,
    }


@app.command()
@handle_errors("status")
def status(ctx: typer.Context) -> None:
    workspace = load_workspace(required=False)
    result = status_result(workspace)
    human = "Documentledger initialized." if result["initialized"] else "Documentledger is not initialized."
    emit(ctx, "status", result, human)


@app.command()
@handle_errors("doctor")
def doctor(ctx: typer.Context) -> None:
    workspace = load_workspace()
    issues: list[dict[str, str]] = []
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
    audit = audit_links(workspace)
    issues.extend(list(audit.get("issues", [])))
    result = {"ok": not issues, "issues": issues}
    emit(ctx, "doctor", result, "Doctor passed." if not issues else "Doctor found issues.")


@app.command()
@handle_errors("scan")
def scan(ctx: typer.Context) -> None:
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
    emit(ctx, "scan", result, human)


@sources_app.command("list")
@handle_errors("sources list")
def sources_list(ctx: typer.Context, path: str | None = typer.Option(None, "--path")) -> None:
    workspace = load_workspace()
    inventory = current_source_inventory(workspace)
    selected = sorted(
        (unit for unit in inventory.values() if path is None or str(unit.get("path", "")) == normalize_repo_path(path)),
        key=lambda item: str(item.get("source_id", "")),
    )
    emit(ctx, "sources list", {"sources": selected}, "\n".join(str(item["source_id"]) for item in selected) or "No source units.")


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


@links_app.command("import-map")
@handle_errors("links import-map")
def links_import_map(
    ctx: typer.Context,
    file_path: str = typer.Option(..., "--file"),
    validate: bool = typer.Option(False, "--validate"),
    apply: bool = typer.Option(False, "--apply"),
    replace_section: bool = typer.Option(False, "--replace-section"),
) -> None:
    if validate == apply:
        raise DocumentledgerError("invalid_selector", "Choose exactly one of --validate or --apply.")
    result = import_mapping(load_workspace(), file_path, apply_changes=apply, replace_section=replace_section)
    emit(ctx, "links import-map", result, "Mapping validated." if validate else "Mapping applied.")


@links_app.command("audit")
@handle_errors("links audit")
def links_audit(ctx: typer.Context) -> None:
    result = audit_links(load_workspace())
    emit(ctx, "links audit", result, "Link audit passed." if result["ok"] else "Link audit found issues.")


@docs_app.command("list")
@handle_errors("docs list")
def docs_list(ctx: typer.Context) -> None:
    scan_record = latest_scan(load_workspace())
    docs = sorted((scan_record or {}).get("doc_hashes", {}).keys())
    emit(ctx, "docs list", {"docs": docs}, "\n".join(docs) or "No docs.")


@docs_app.command("sections")
@handle_errors("docs sections")
def docs_sections(
    ctx: typer.Context,
    doc: str | None = typer.Option(None, "--doc"),
    all_docs: bool = typer.Option(False, "--all"),
) -> None:
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
                "sections": [section.to_record() for section in doc_sections_for_file(workspace.config.root / doc_path, doc_path)],
            }
            for doc_path in docs_to_read
        ]
    }
    human = "\n".join(doc_path for doc_path in docs_to_read)
    emit(ctx, "docs sections", result, human or "No docs.")


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
    include_unlinked: bool = typer.Option(False, "--include-unlinked"),
    out: str | None = typer.Option(None, "--out"),
    print_output: bool = typer.Option(False, "--print"),
) -> None:
    workspace = load_workspace()
    if doc and all_docs:
        raise DocumentledgerError("invalid_selector", "Use --doc or --all, not both.")
    if section and not doc:
        raise DocumentledgerError("doc_required", "Use --doc when selecting --section.")
    selected = [normalize_repo_path(doc)] if doc else None
    content = render_context(workspace, selected, section_id=section, include_unlinked=include_unlinked)
    if out:
        atomic_write_text(Path(out), content)
    else:
        rendered = workspace.config.storage_dir / "rendered" / "latest-context.md"
        atomic_write_text(rendered, content)
    if print_output or not ctx.obj.get("json"):
        typer.echo(content)
    elif ctx.obj.get("json"):
        result = {"path": str(out) if out else None, "affected": affected or True}
        typer.echo(json.dumps(envelope("docs build-context", result), sort_keys=True))


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
