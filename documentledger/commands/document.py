"""Document commands: list, sections, affected, stale, build-context, mark-fresh."""

from __future__ import annotations

from pathlib import Path
from time import perf_counter
from typing import Any

import typer
from ledgercore.atomic import atomic_write_text

from documentledger.cli_support import emit_success, get_state, handle_command_error
from documentledger.errors import DocumentledgerError
from documentledger.identity import normalize_repo_path
from documentledger.storage import (
    load_workspace,
)


def _profile_events(ctx: typer.Context, operation: str, started_at: float) -> list[dict[str, Any]]:
    state = get_state(ctx)
    if not state.json_output:
        return []
    return [{"event": "profile", "operation": operation, "elapsed_ms": round((perf_counter() - started_at) * 1000, 3)}]


def register_document_commands(app: typer.Typer, docs_app: typer.Typer) -> None:  # noqa: C901
    """Register document commands on the docs app and as aliases on the main app."""

    @docs_app.command("list")
    @handle_command_error("document list")
    def document_list(ctx: typer.Context) -> None:
        started_at = perf_counter()
        state = get_state(ctx)
        from documentledger.scanner import collect_files

        workspace = load_workspace(start=state.root)
        docs = collect_files(workspace, workspace.config.doc_roots, workspace.config.doc_extensions)
        emit_success(ctx, "document list", {"docs": docs}, "\n".join(docs) or "No docs.", _profile_events(ctx, "document list", started_at))

    @docs_app.command("sections")
    @handle_command_error("document sections")
    def document_sections(
        ctx: typer.Context,
        doc: str | None = typer.Option(None, "--doc"),
        all_docs: bool = typer.Option(False, "--all"),
        ids_only: bool = typer.Option(False, "--ids-only"),
        outline: bool = typer.Option(False, "--outline"),
    ) -> None:
        from documentledger.doc_index import doc_sections_for_file
        from documentledger.scanner import collect_files

        started_at = perf_counter()
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
        emit_success(ctx, "document sections", result, human or "No docs.", _profile_events(ctx, "document sections", started_at))

    @docs_app.command("affected")
    @handle_command_error("document affected")
    def document_affected(ctx: typer.Context, doc: str | None = typer.Option(None, "--doc")) -> None:
        state = get_state(ctx)
        workspace = load_workspace(start=state.root)
        from documentledger.impact import resolve_affected_sections

        docs = [normalize_repo_path(doc)] if doc else None
        affected = resolve_affected_sections(workspace, docs=docs)
        human = ["Affected documentation sections:"]
        if not affected:
            human.append("- None")
        for item in affected:
            heading = " / ".join(item["heading_path"]) or item["section_id"]
            human.append(f"- {item['doc_path']} :: {heading}")
        emit_success(ctx, "document affected", {"affected_sections": affected}, "\n".join(human))

    @docs_app.command("stale")
    @handle_command_error("document stale")
    def document_stale(ctx: typer.Context) -> None:
        state = get_state(ctx)
        from documentledger.render import stale_details

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

    @docs_app.command("build-context")
    @handle_command_error("document build-context")
    def document_build_context(
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
        from documentledger.render import render_context

        started_at = perf_counter()
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
            typer.echo(rendered["content"])
        result = {key: value for key, value in rendered.items() if key != "content"} | {"path": str(output_path)}
        human = str(rendered["content"]) if print_output else f"Saved context to {output_path}"
        emit_success(ctx, "document build-context", result, human, _profile_events(ctx, "document build-context", started_at))

    @docs_app.command("mark-fresh")
    @handle_command_error("document mark-fresh")
    def document_mark_fresh(
        ctx: typer.Context,
        doc: str | None = typer.Option(None, "--doc"),
        section: str | None = typer.Option(None, "--section"),
        all_docs: bool = typer.Option(False, "--all"),
        affected: bool = typer.Option(False, "--affected"),
        allow_unlinked: bool = typer.Option(False, "--allow-unlinked"),
        reason: str = typer.Option(..., "--reason"),
    ) -> None:
        state = get_state(ctx)
        workspace = load_workspace(start=state.root)
        from documentledger.freshness import mark_fresh

        result = mark_fresh(
            workspace,
            doc=doc,
            section=section,
            all_docs=all_docs,
            affected=affected,
            allow_unlinked=allow_unlinked,
            reason=reason,
        )
        emit_success(
            ctx,
            "document mark-fresh",
            result,
            "Marked docs fresh.",
        )
