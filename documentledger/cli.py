from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from documentledger.errors import DocumentledgerError
from documentledger.identity import normalize_repo_path
from documentledger.links import add_link, list_links, remove_link
from documentledger.render import render_context, stale_details
from documentledger.scanner import file_hash, run_scan
from documentledger.storage import (
    init_workspace,
    iter_doc_records,
    latest_scan,
    load_doc_record,
    load_workspace,
    now_iso,
    save_doc_record,
)

app = typer.Typer(no_args_is_help=True)
links_app = typer.Typer(no_args_is_help=True)
docs_app = typer.Typer(no_args_is_help=True)
app.add_typer(links_app, name="links")
app.add_typer(docs_app, name="docs")


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


def fail(command: str, exc: DocumentledgerError) -> None:
    typer.echo(json.dumps(error_envelope(command, exc), sort_keys=True))
    raise typer.Exit(exc.exit_code) from exc


@app.callback()
def main(ctx: typer.Context, json_output: bool = typer.Option(False, "--json", help="Emit JSON envelope.")) -> None:
    ctx.obj = {"json": json_output}


@app.command()
def init(
    ctx: typer.Context,
    project_name: str | None = typer.Option(None, "--project-name"),
    documentledger_dir: str = typer.Option(".documentledger", "--documentledger-dir"),
    hidden_config: bool = typer.Option(False, "--hidden-config"),
) -> None:
    try:
        workspace = init_workspace(project_name, documentledger_dir, hidden_config)
    except DocumentledgerError as exc:
        fail("init", exc)
    result = status_result(workspace)
    emit(ctx, "init", result, f"Initialized Documentledger for {workspace.config.project_name}")


def status_result(workspace: Any | None) -> dict[str, Any]:
    if workspace is None:
        return {
            "initialized": False,
            "config_path": None,
            "storage_dir": None,
            "project_name": None,
            "project_uuid": None,
            "last_scan_id": None,
            "remediation": ["Run `docledger init` from the project root."],
        }
    config_rel = workspace.config.path.relative_to(workspace.config.root).as_posix()
    storage_rel = workspace.config.storage_dir.relative_to(workspace.config.root).as_posix()
    return {
        "initialized": True,
        "config_path": config_rel,
        "storage_dir": storage_rel,
        "project_name": workspace.config.project_name,
        "project_uuid": workspace.metadata.get("project_uuid") or workspace.config.project_uuid,
        "last_scan_id": workspace.metadata.get("last_scan_id") or None,
    }


@app.command()
def status(ctx: typer.Context) -> None:
    workspace = load_workspace(required=False)
    result = status_result(workspace)
    human = "Documentledger initialized." if result["initialized"] else "Documentledger is not initialized."
    emit(ctx, "status", result, human)


@app.command()
def doctor(ctx: typer.Context) -> None:
    workspace = load_workspace()
    issues: list[dict[str, str]] = []
    if workspace.metadata.get("schema_version") != 1:
        issues.append({"code": "schema_mismatch", "message": "storage.yaml schema_version is not 1"})
    seen: set[tuple[str, str]] = set()
    for record in iter_doc_records(workspace):
        doc_path = str(record.get("doc_path", ""))
        try:
            normalize_repo_path(doc_path)
        except DocumentledgerError as exc:
            issues.append({"code": exc.code, "message": exc.message})
        if not (workspace.config.root / doc_path).exists():
            issues.append({"code": "missing_doc", "message": f"Missing doc file: {doc_path}"})
        for source in record.get("linked_sources", []) or []:
            key = (doc_path, str(source))
            if key in seen:
                issues.append({"code": "duplicate_link", "message": f"Duplicate link: {doc_path} -> {source}"})
            seen.add(key)
            if not (workspace.config.root / str(source)).exists():
                issues.append({"code": "missing_source", "message": f"Missing source file: {source}"})
    result = {"ok": not issues, "issues": issues}
    emit(ctx, "doctor", result, "Doctor passed." if not issues else "Doctor found issues.")


@app.command()
def scan(ctx: typer.Context) -> None:
    result_obj = run_scan(load_workspace())
    result = {
        "scan_id": result_obj.scan_id,
        "changed_sources": result_obj.changed_sources,
        "deleted_sources": result_obj.deleted_sources,
        "stale_docs": result_obj.stale_docs,
        "unlinked_changed_sources": result_obj.unlinked_changed_sources,
    }
    emit(ctx, "scan", result, f"Recorded {result_obj.scan_id}")


@links_app.command("list")
def links_list(ctx: typer.Context) -> None:
    records = list_links(load_workspace())
    emit(ctx, "links list", {"docs": records}, "\n".join(str(r["doc_path"]) for r in records) or "No links.")


@links_app.command("add")
def links_add(
    ctx: typer.Context,
    doc: str = typer.Option(..., "--doc"),
    source: str = typer.Option(..., "--source"),
    reason: str | None = typer.Option(None, "--reason"),
) -> None:
    try:
        record = add_link(load_workspace(), doc, source, reason)
    except DocumentledgerError as exc:
        fail("links add", exc)
    emit(ctx, "links add", record, f"Linked {source} to {doc}")


@links_app.command("remove")
def links_remove(ctx: typer.Context, doc: str = typer.Option(..., "--doc"), source: str = typer.Option(..., "--source")) -> None:
    record = remove_link(load_workspace(), doc, source)
    emit(ctx, "links remove", record, f"Removed {source} from {doc}")


@docs_app.command("list")
def docs_list(ctx: typer.Context) -> None:
    scan_record = latest_scan(load_workspace())
    docs = sorted((scan_record or {}).get("doc_hashes", {}).keys())
    emit(ctx, "docs list", {"docs": docs}, "\n".join(docs) or "No docs.")


@docs_app.command("stale")
def docs_stale(ctx: typer.Context) -> None:
    details = stale_details(load_workspace())
    human = ["Stale documentation:"]
    if not details:
        human.append("- None")
    for item in details:
        human.extend([f"- {item['doc_path']}", "  Changed sources:"])
        human.extend(f"  - {source}" for source in item["changed_sources"])
        human.append("  Deleted sources:")
        human.extend(f"  - {source}" for source in item["deleted_sources"])
    emit(ctx, "docs stale", {"stale_docs": details}, "\n".join(human))


@docs_app.command("build-context")
def docs_build_context(
    ctx: typer.Context,
    doc: str | None = typer.Option(None, "--doc"),
    all_docs: bool = typer.Option(False, "--all"),
    out: str | None = typer.Option(None, "--out"),
    print_output: bool = typer.Option(False, "--print"),
) -> None:
    workspace = load_workspace()
    if doc and all_docs:
        raise DocumentledgerError("invalid_selector", "Use --doc or --all, not both.")
    selected = [normalize_repo_path(doc)] if doc else None
    content = render_context(workspace, selected)
    if out:
        Path(out).write_text(content, encoding="utf-8")
    else:
        rendered = workspace.config.storage_dir / "rendered" / "latest-context.md"
        rendered.parent.mkdir(parents=True, exist_ok=True)
        rendered.write_text(content, encoding="utf-8")
    if print_output or not ctx.obj.get("json"):
        typer.echo(content)
    elif ctx.obj.get("json"):
        typer.echo(json.dumps(envelope("docs build-context", {"path": str(out) if out else None}), sort_keys=True))


@app.command("mark-fresh")
def mark_fresh(
    ctx: typer.Context,
    doc: str | None = typer.Option(None, "--doc"),
    all_docs: bool = typer.Option(False, "--all"),
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
    docs = [normalize_repo_path(doc)] if doc else list(scan_record.get("stale_docs", []) or []) if all_docs else []
    if not docs:
        raise DocumentledgerError("doc_required", "Select --doc DOC or --all.")
    updated = []
    for doc_path in docs:
        record = load_doc_record(workspace, doc_path) or {
            "schema": "documentledger.doc_record.v1",
            "doc_path": doc_path,
            "linked_sources": [],
            "notes": "",
        }
        record["last_fresh_scan_id"] = scan_record["scan_id"]
        record["last_fresh_hash"] = file_hash(workspace.config.root / doc_path)
        record["updated_at"] = now_iso()
        record["notes"] = reason
        save_doc_record(workspace, record)
        updated.append(doc_path)
    emit(ctx, "mark-fresh", {"updated_docs": updated, "scan_id": scan_record["scan_id"]}, "Marked docs fresh.")


def run() -> None:
    try:
        app()
    except DocumentledgerError as exc:
        command = "unknown"
        typer.echo(json.dumps(error_envelope(command, exc), sort_keys=True), err=False)
        raise typer.Exit(exc.exit_code) from exc
