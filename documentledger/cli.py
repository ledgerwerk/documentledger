"""Unified Documentledger CLI.

This module creates the Typer applications, registers command groups,
and defines the root callback with global options.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import typer
from ledgercore.cli import CLIWarning, CommonCLIState

from documentledger.cli_support import version_callback

# Main application
app = typer.Typer(no_args_is_help=True)

# Command groups (canonical singular names)
document_app = typer.Typer(no_args_is_help=True)
source_app = typer.Typer(no_args_is_help=True)
link_app = typer.Typer(no_args_is_help=True)
storage_app = typer.Typer(no_args_is_help=True)
migrate_app = typer.Typer(no_args_is_help=True)
config_app = typer.Typer(no_args_is_help=True)
schema_app = typer.Typer(no_args_is_help=True)

# Register canonical groups
app.add_typer(document_app, name="document")
app.add_typer(source_app, name="source")
app.add_typer(link_app, name="link")
app.add_typer(storage_app, name="storage")
app.add_typer(migrate_app, name="migrate")
app.add_typer(config_app, name="config")
app.add_typer(schema_app, name="schema")

# Register plural aliases as hidden groups
docs_alias = typer.Typer(no_args_is_help=True, hidden=True)
sources_alias = typer.Typer(no_args_is_help=True, hidden=True)
links_alias = typer.Typer(no_args_is_help=True, hidden=True)
app.add_typer(docs_alias, name="docs")
app.add_typer(sources_alias, name="sources")
app.add_typer(links_alias, name="links")


def _initial_warnings() -> tuple[CLIWarning, ...]:
    """Collect any startup warnings."""
    return ()


@app.callback()
def main(
    ctx: typer.Context,
    root: Path = typer.Option(
        Path("."),
        "--root",
        exists=False,
        file_okay=False,
        dir_okay=True,
        resolve_path=False,
        help="Project root directory.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON envelope."),
    profile: bool = typer.Option(False, "--profile", hidden=True, help="Emit profiling metadata."),
    version: bool = typer.Option(
        False,
        "--version",
        is_eager=True,
        callback=version_callback,
        help="Show version and exit.",
    ),
) -> None:
    ctx.obj = {
        "state": CommonCLIState(
            tool="documentledger",
            root=root.resolve(strict=False),
            json_output=json_output,
            warnings=_initial_warnings(),
        ),
        "profile": profile or os.getenv("DOCLEDGER_PROFILE") == "1",
    }


def register_commands() -> None:
    """Register all command modules."""
    from documentledger.commands.config import register_config_commands
    from documentledger.commands.document import register_document_commands
    from documentledger.commands.link import register_link_commands
    from documentledger.commands.migrate import register_migrate_commands
    from documentledger.commands.root import register_root_commands
    from documentledger.commands.schema import register_schema_commands
    from documentledger.commands.source import register_source_commands
    from documentledger.commands.storage import register_storage_commands

    register_root_commands(app)
    register_document_commands(app, document_app)
    register_source_commands(app, source_app)
    register_link_commands(app, link_app)
    register_storage_commands(app, storage_app)
    register_migrate_commands(app, migrate_app, storage_app)
    register_config_commands(app, config_app)
    register_schema_commands(app, schema_app)

    # Register plural aliases - they call the same handlers
    _register_aliases()


def _register_aliases() -> None:
    """Register plural alias commands that delegate to canonical handlers."""
    _register_docs_aliases()
    _register_sources_aliases()
    _register_links_aliases()
    _register_mark_fresh_alias()


def _register_docs_aliases() -> None:
    """Register docs -> document alias commands."""
    from documentledger.cli_support import emit_success, get_state, handle_command_error
    from documentledger.errors import DocumentledgerError
    from documentledger.storage import load_workspace

    # docs list -> document list
    @docs_alias.command("list")
    @handle_command_error("docs list")
    def docs_list(ctx: typer.Context) -> None:
        from documentledger.scanner import collect_files

        state = get_state(ctx)
        workspace = load_workspace(start=state.root)
        docs = collect_files(workspace, workspace.config.doc_roots, workspace.config.doc_extensions)
        emit_success(ctx, "document list", {"docs": docs}, "\n".join(docs) or "No docs.")

    # docs sections -> document sections
    @docs_alias.command("sections")
    @handle_command_error("docs sections")
    def docs_sections(
        ctx: typer.Context,
        doc: str | None = typer.Option(None, "--doc"),
        all_docs: bool = typer.Option(False, "--all"),
        ids_only: bool = typer.Option(False, "--ids-only"),
        outline: bool = typer.Option(False, "--outline"),
    ) -> None:
        from documentledger.doc_index import doc_sections_for_file
        from documentledger.identity import normalize_repo_path
        from documentledger.scanner import collect_files

        state = get_state(ctx)
        workspace = load_workspace(start=state.root)
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
                        str(section.section_id) if ids_only else section.to_record()
                        for section in doc_sections_for_file(workspace.config.root / doc_path, doc_path)
                    ],
                }
                for doc_path in docs_to_read
            ]
        }
        human = "\n".join(doc_path for doc_path in docs_to_read)
        emit_success(ctx, "document sections", result, human or "No docs.")

    # docs affected -> document affected
    @docs_alias.command("affected")
    @handle_command_error("docs affected")
    def docs_affected(ctx: typer.Context, doc: str | None = typer.Option(None, "--doc")) -> None:
        from documentledger.identity import normalize_repo_path
        from documentledger.impact import resolve_affected_sections

        state = get_state(ctx)
        workspace = load_workspace(start=state.root)
        docs = [normalize_repo_path(doc)] if doc else None
        affected = resolve_affected_sections(workspace, docs=docs)
        human = ["Affected documentation sections:"]
        if not affected:
            human.append("- None")
        for item in affected:
            heading = " / ".join(item["heading_path"]) or item["section_id"]
            human.append(f"- {item['doc_path']} :: {heading}")
        emit_success(ctx, "document affected", {"affected_sections": affected}, "\n".join(human))

    # docs stale -> document stale
    @docs_alias.command("stale")
    @handle_command_error("docs stale")
    def docs_stale(ctx: typer.Context) -> None:
        from documentledger.render import stale_details

        state = get_state(ctx)
        details = stale_details(load_workspace(start=state.root))
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
        emit_success(ctx, "document stale", {"stale_docs": details}, "\n".join(human))

    # docs build-context -> document build-context
    @docs_alias.command("build-context")
    @handle_command_error("docs build-context")
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
        from pathlib import Path

        from ledgercore.atomic import atomic_write_text

        from documentledger.identity import normalize_repo_path
        from documentledger.render import render_context

        state = get_state(ctx)
        workspace = load_workspace(start=state.root)
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
        artifacts_dir = getattr(getattr(workspace, "paths", None), "artifacts_dir", None)
        if (
            out is None
            and artifacts_dir is not None
            and getattr(workspace.paths, "layout_source", "legacy") == "canonical"
            and not artifacts_dir.exists()
        ):
            import ledgercore

            from documentledger.project import resolve_canonical_project

            canonical = resolve_canonical_project(workspace.paths.project_root, require_data=True)
            ledgercore.initialize_storage_binding(canonical.layout.mounts["artifacts"], require_empty=True)
        output_path = (
            Path(out)
            if out
            else (
                artifacts_dir / "rendered" / "latest-context.md"
                if artifacts_dir
                else workspace.config.storage_dir / "rendered" / "latest-context.md"
            )
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(output_path, str(rendered["content"]))
        if print_output and state.json_output:
            import typer as t

            t.echo(rendered["content"])
        result = {key: value for key, value in rendered.items() if key != "content"} | {"path": str(output_path)}
        human_out = str(rendered["content"]) if print_output else f"Saved context to {output_path}"
        emit_success(ctx, "document build-context", result, human_out)


def _register_sources_aliases() -> None:
    """Register sources -> source alias commands."""
    from documentledger.cli_support import emit_success, get_state, handle_command_error
    from documentledger.errors import DocumentledgerError
    from documentledger.storage import load_workspace

    # sources list -> source list
    @sources_alias.command("list")
    @handle_command_error("sources list")
    def sources_list(
        ctx: typer.Context,
        kind: list[str] = typer.Option(None, "--kind"),
        path: str | None = typer.Option(None, "--path"),
        path_prefix: str | None = typer.Option(None, "--path-prefix"),
        qualname: str | None = typer.Option(None, "--qualname"),
        query: str | None = typer.Option(None, "--query"),
        ids_only: bool = typer.Option(False, "--ids-only"),
        include_hashes: bool = typer.Option(False, "--include-hashes"),
        limit: int = typer.Option(100, "--limit"),
        cursor: str | None = typer.Option(None, "--cursor"),
    ) -> None:
        from documentledger.commands.source import _normalize_cursor, _trim_source_record
        from documentledger.identity import normalize_repo_path
        from documentledger.links import current_source_inventory

        state = get_state(ctx)
        workspace = load_workspace(start=state.root)
        inventory = current_source_inventory(workspace)
        selected = sorted(inventory.values(), key=lambda item: str(item.get("source_id", "")))
        kind = kind or []
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
        offset = _normalize_cursor(cursor)
        page = selected[offset : offset + max(limit, 0)]
        next_cursor = offset + len(page) if offset + len(page) < len(selected) else None
        result_sources = (
            [str(item.get("source_id", "")) for item in page]
            if ids_only
            else [_trim_source_record(dict(item), include_hashes=include_hashes) for item in page]
        )
        result = {"sources": result_sources, "count": len(page), "total": len(selected), "next_cursor": next_cursor}
        human = "\n".join(str(item["source_id"]) for item in page) or "No source units."
        emit_success(ctx, "source list", result, human)

    # sources show -> source show
    @sources_alias.command("show")
    @handle_command_error("sources show")
    def sources_show(ctx: typer.Context, source_id: str = typer.Argument(...)) -> None:
        from documentledger.links import current_source_inventory

        state = get_state(ctx)
        inventory = current_source_inventory(load_workspace(start=state.root))
        if source_id not in inventory:
            raise DocumentledgerError("source_unit_not_found", f"Unknown source unit: {source_id}")
        emit_success(ctx, "source show", inventory[source_id], source_id)


def _register_links_aliases() -> None:
    """Register links -> link alias commands."""
    from documentledger.cli_support import emit_success, get_state, handle_command_error
    from documentledger.errors import DocumentledgerError
    from documentledger.storage import load_workspace

    # links list -> link list
    @links_alias.command("list")
    @handle_command_error("links list")
    def links_list(ctx: typer.Context) -> None:
        from documentledger.links import list_links

        state = get_state(ctx)
        records = list_links(load_workspace(start=state.root))
        emit_success(ctx, "link list", {"docs": records}, "\n".join(str(r["doc_path"]) for r in records) or "No links.")

    # links add -> link add
    @links_alias.command("add")
    @handle_command_error("links add")
    def links_add(
        ctx: typer.Context,
        doc: str = typer.Option(..., "--doc"),
        source: str = typer.Option(..., "--source"),
        reason: str | None = typer.Option(None, "--reason"),
    ) -> None:
        from documentledger.links import add_link

        state = get_state(ctx)
        record = add_link(load_workspace(start=state.root), doc, source, reason)
        emit_success(ctx, "link add", record, f"Linked {source} to {doc}")

    # links remove -> link remove
    @links_alias.command("remove")
    @handle_command_error("links remove")
    def links_remove(ctx: typer.Context, doc: str = typer.Option(..., "--doc"), source: str = typer.Option(..., "--source")) -> None:
        from documentledger.links import remove_link

        state = get_state(ctx)
        record = remove_link(load_workspace(start=state.root), doc, source)
        emit_success(ctx, "link remove", record, f"Removed {source} from {doc}")

    # links add-section -> link add-section
    @links_alias.command("add-section")
    @handle_command_error("links add-section")
    def links_add_section(
        ctx: typer.Context,
        doc: str = typer.Option(..., "--doc"),
        section: str = typer.Option(..., "--section"),
        source_unit: str = typer.Option(..., "--source-unit"),
        coverage: str = typer.Option(..., "--coverage"),
        impact: str = typer.Option(..., "--impact"),
        reason: str = typer.Option(..., "--reason"),
    ) -> None:
        from documentledger.links import add_section_link

        state = get_state(ctx)
        record = add_section_link(load_workspace(start=state.root), doc, section, source_unit, coverage, impact, reason)
        emit_success(ctx, "link add-section", record, f"Linked {source_unit} to {doc} section {section}")

    # links remove-section -> link remove-section
    @links_alias.command("remove-section")
    @handle_command_error("links remove-section")
    def links_remove_section(
        ctx: typer.Context,
        doc: str = typer.Option(..., "--doc"),
        section: str = typer.Option(..., "--section"),
        source_unit: str = typer.Option(..., "--source-unit"),
    ) -> None:
        from documentledger.links import remove_section_link

        state = get_state(ctx)
        record = remove_section_link(load_workspace(start=state.root), doc, section, source_unit)
        emit_success(ctx, "link remove-section", record, f"Removed {source_unit} from {doc} section {section}")

    # links import-map -> link import-map
    @links_alias.command("import-map")
    @handle_command_error("links import-map")
    def links_import_map(
        ctx: typer.Context,
        file_path: list[str] = typer.Option(None, "--file"),
        directory: str | None = typer.Option(None, "--directory"),
        validate: bool = typer.Option(False, "--validate"),
        apply: bool = typer.Option(False, "--apply"),
        check_and_apply: bool = typer.Option(False, "--check-and-apply"),
        replace_section: bool = typer.Option(False, "--replace-section"),
    ) -> None:
        from pathlib import Path

        from documentledger.links import apply_mapping_batch, prepare_mapping_batch

        file_path = file_path or []
        mode_count = sum(bool(value) for value in (validate, apply, check_and_apply))
        if mode_count != 1:
            raise DocumentledgerError("invalid_selector", "Choose exactly one of --validate, --apply, or --check-and-apply.")
        mapping_paths = [Path(path) for path in file_path]
        if directory is not None:
            mapping_paths.extend(sorted(Path(directory).glob("*.yaml")))
        if not mapping_paths:
            raise DocumentledgerError("invalid_mapping", "Provide at least one --file or a --directory.")
        state = get_state(ctx)
        workspace = load_workspace(start=state.root)
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
            emit_success(ctx, "link import-map", result, "Mapping validated.", events)
            return
        result = apply_mapping_batch(workspace, prepared, replace_sections=replace_section) | {"applied": True}
        for doc_path in sorted(prepared.documents):
            events.append({"event": "document_saved", "doc": doc_path})
        emit_success(ctx, "link import-map", result, "Mapping applied." if apply else "Mapping validated and applied.", events)

    # links audit -> link audit
    @links_alias.command("audit")
    @handle_command_error("links audit")
    def links_audit(ctx: typer.Context) -> None:
        from documentledger.links import audit_links

        state = get_state(ctx)
        result = audit_links(load_workspace(start=state.root))
        emit_success(ctx, "link audit", result, "Link audit passed." if result["ok"] else "Link audit found issues.")

    # links propose -> link propose
    @links_alias.command("propose")
    @handle_command_error("links propose")
    def links_propose(
        ctx: typer.Context,
        all_docs: bool = typer.Option(False, "--all-docs"),
        out_dir: str | None = typer.Option(None, "--out-dir"),
    ) -> None:
        _handle_links_propose(ctx, all_docs, out_dir, get_state, emit_success, load_workspace)


def _proposal_links_for_section(section_text: str, inv: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Find source-link proposals for a single document section."""
    proposals: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for unit in sorted(inv.values(), key=lambda i: (str(i.get("path", "")), str(i.get("source_id", "")))):
        sp = str(unit.get("path", ""))
        qn = str(unit.get("qualname", ""))
        mt: str | None = None
        reason: str | None = None
        evidence_kind: str | None = None
        if sp and sp in section_text:
            mt, reason, evidence_kind = sp, f"Section contains exact source path `{sp}`.", "exact-source-reference"
        elif qn and qn != sp and qn in section_text:
            mt, reason, evidence_kind = qn, f"Section contains exact qualified symbol `{qn}`.", "exact-qualified-symbol"
        if mt is None:
            continue
        sid = str(unit.get("source_id", ""))
        dedup_key = (sid, "implementation-note", "unknown")
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        proposals.append(
            {
                "source_unit": sid,
                "coverage": "implementation-note",
                "impact": "unknown",
                "reason": reason,
                "confidence": "high",
                "evidence": {"kind": evidence_kind, "text": mt},
            }
        )
    return proposals


def _ensure_artifacts_dir(workspace: object, out_dir_str: str | None, artifacts_dir: Path | None) -> Path:
    """Return output_dir, initialising the artifacts binding if needed."""
    from pathlib import Path

    output_dir = (
        Path(out_dir_str)
        if out_dir_str
        else (
            (artifacts_dir / "proposals") if artifacts_dir else workspace.config.storage_dir / "proposals"  # type: ignore[union-attr]
        )
    )
    if (
        out_dir_str is None
        and artifacts_dir is not None
        and getattr(workspace.paths, "layout_source", "legacy") == "canonical"  # type: ignore[union-attr]
        and not artifacts_dir.exists()
    ):
        import ledgercore

        from documentledger.project import resolve_canonical_project

        canonical = resolve_canonical_project(workspace.paths.project_root, require_data=True)  # type: ignore[union-attr]
        ledgercore.initialize_storage_binding(canonical.layout.mounts["artifacts"], require_empty=True)
    return output_dir


def _handle_links_propose(
    ctx: typer.Context,
    all_docs: bool,
    out_dir: str | None,
    get_state: object,
    emit_success: object,
    load_workspace: object,
) -> None:
    """Implementation of links propose, extracted for complexity control."""
    from pathlib import Path

    from ledgercore.yamlio import write_yaml as core_write_yaml

    from documentledger.doc_index import doc_sections_for_file
    from documentledger.errors import DocumentledgerError
    from documentledger.links import current_source_inventory
    from documentledger.scanner import collect_files

    if not all_docs:
        raise DocumentledgerError("invalid_selector", "Use --all-docs for proposal generation.")
    state = get_state(ctx)  # type: ignore[operator]
    workspace = load_workspace(start=state.root)  # type: ignore[operator]
    inventory = current_source_inventory(workspace)
    docs = collect_files(workspace, workspace.config.doc_roots, workspace.config.doc_extensions)
    artifacts_dir = getattr(getattr(workspace, "paths", None), "artifacts_dir", None)
    output_dir = _ensure_artifacts_dir(workspace, out_dir, artifacts_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    written_files: list[str] = []
    proposed_sections = 0
    proposed_edges = 0
    events: list[dict[str, Any]] = []
    for doc_path in docs:
        sections_payload = []
        for section in doc_sections_for_file(workspace.config.root / doc_path, doc_path):
            links = _proposal_links_for_section(section.text, inventory)
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
    emit_success(ctx, "link propose", result, f"Wrote {len(written_files)} proposal files.", events)  # type: ignore[operator]


def _register_mark_fresh_alias() -> None:
    """Register the legacy mark-fresh root command alias."""
    from documentledger.cli_support import emit_success, get_state, handle_command_error
    from documentledger.errors import DocumentledgerError
    from documentledger.storage import load_workspace

    @app.command("mark-fresh")
    @handle_command_error("mark-fresh")
    def mark_fresh(
        ctx: typer.Context,
        doc: str | None = typer.Option(None, "--doc"),
        section: str | None = typer.Option(None, "--section"),
        all_docs: bool = typer.Option(False, "--all"),
        allow_unlinked: bool = typer.Option(False, "--allow-unlinked"),
        reason: str = typer.Option(..., "--reason"),
    ) -> None:
        """Legacy alias: use 'document mark-fresh' instead."""
        from documentledger.cli_support import CLIWarning

        state = get_state(ctx)
        state = state.with_warning(
            CLIWarning(
                code="deprecated-command",
                message="'mark-fresh' is deprecated. Use 'document mark-fresh'.",
                replacement="document mark-fresh",
            )
        )
        ctx.obj["state"] = state
        # Delegate to the canonical handler
        import json

        from documentledger.commands.document import _selected_sections_for_mark_fresh
        from documentledger.doc_index import doc_sections_for_file
        from documentledger.identity import normalize_repo_path
        from documentledger.impact import resolve_affected_sections
        from documentledger.links import current_source_inventory
        from documentledger.scanner import file_hash
        from documentledger.storage import latest_scan, save_doc_record

        if not reason.strip():
            raise DocumentledgerError("reason_required", "mark-fresh requires a non-empty reason.")
        workspace = load_workspace(start=state.root)
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
        updated_docs, updated_sections = [], []
        for doc_path in doc_paths:
            record, sections = _selected_sections_for_mark_fresh(workspace, doc_path, section, allow_unlinked)
            before = json.dumps(record, sort_keys=True)
            for sel in sections:
                for cur in doc_sections_for_file(workspace.config.root / doc_path, doc_path):
                    if cur.section_id != str(sel.get("section_id")):
                        continue
                    sel["heading_path"] = list(cur.heading_path)
                    sel["heading_slug"] = cur.heading_slug
                    sel["line_span"] = [cur.line_span[0], cur.line_span[1]]
                    sel["section_hash"] = cur.section_hash
                    sel["summary"] = cur.summary
                    break
                for link in sel.get("links", []) or []:
                    sid = str(link.get("source_id", ""))
                    if sid not in inventory:
                        raise DocumentledgerError("source_unit_not_found", f"Cannot mark fresh while linked source unit is missing: {sid}")
                    cu = inventory[sid]
                    tracked = dict(link.get("tracked_hashes", {}))
                    link["tracked_hashes"] = {n: str(cu["hashes"][n]) for n in tracked if n in cu.get("hashes", {})}
                updated_sections.append(f"{doc_path}::{sel['heading_slug']}")
            record["last_fresh_scan_version"] = scan_record["version"]
            record["last_fresh_hash"] = file_hash(workspace.config.root / doc_path)
            record["notes"] = reason if record.get("linked_sources") else f"{reason} (intentionally unlinked)"
            if json.dumps(record, sort_keys=True) != before:
                save_doc_record(workspace, record)
            updated_docs.append(doc_path)
        emit_success(
            ctx,
            "mark-fresh",
            {"updated_docs": updated_docs, "updated_sections": updated_sections, "scan_version": scan_record["version"]},
            "Marked docs fresh.",
        )


# Register commands on import
register_commands()


def run() -> None:
    """CLI entry point."""
    import typer as t

    from documentledger.errors import DocumentledgerError

    try:
        app()
    except DocumentledgerError as exc:
        t.echo(f"Error: {exc.message}", err=True)
        raise t.Exit(code=exc.exit_code) from exc
