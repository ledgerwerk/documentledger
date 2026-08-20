"""Link commands: list, add, remove, add-section, remove-section, import-map, audit, propose."""

from __future__ import annotations

from pathlib import Path
from time import perf_counter
from typing import Any

import typer

from documentledger.cli_support import emit_success, get_state, handle_command_error
from documentledger.errors import DocumentledgerError
from documentledger.storage import load_workspace


def _profile_events(ctx: typer.Context, operation: str, started_at: float) -> list[dict[str, Any]]:
    state = get_state(ctx)
    if not state.json_output:
        return []
    return [{"event": "profile", "operation": operation, "elapsed_ms": round((perf_counter() - started_at) * 1000, 3)}]


def register_link_commands(app: typer.Typer, links_app: typer.Typer) -> None:  # noqa: C901
    """Register link commands on the links app."""

    @links_app.command("list")
    @handle_command_error("link list")
    def link_list(ctx: typer.Context) -> None:
        from documentledger.links import list_links

        state = get_state(ctx)
        records = list_links(load_workspace(start=state.root))
        emit_success(ctx, "link list", {"docs": records}, "\n".join(str(r["doc_path"]) for r in records) or "No links.")

    @links_app.command("add")
    @handle_command_error("link add")
    def link_add(
        ctx: typer.Context,
        doc: str = typer.Option(..., "--doc"),
        source: str = typer.Option(..., "--source"),
        reason: str | None = typer.Option(None, "--reason"),
    ) -> None:
        from documentledger.links import add_link

        state = get_state(ctx)
        record = add_link(load_workspace(start=state.root), doc, source, reason)
        emit_success(ctx, "link add", record, f"Linked {source} to {doc}")

    @links_app.command("remove")
    @handle_command_error("link remove")
    def link_remove(ctx: typer.Context, doc: str = typer.Option(..., "--doc"), source: str = typer.Option(..., "--source")) -> None:
        from documentledger.links import remove_link

        state = get_state(ctx)
        record = remove_link(load_workspace(start=state.root), doc, source)
        emit_success(ctx, "link remove", record, f"Removed {source} from {doc}")

    @links_app.command("add-section")
    @handle_command_error("link add-section")
    def link_add_section(
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

    @links_app.command("remove-section")
    @handle_command_error("link remove-section")
    def link_remove_section(
        ctx: typer.Context,
        doc: str = typer.Option(..., "--doc"),
        section: str = typer.Option(..., "--section"),
        source_unit: str = typer.Option(..., "--source-unit"),
    ) -> None:
        from documentledger.links import remove_section_link

        state = get_state(ctx)
        record = remove_section_link(load_workspace(start=state.root), doc, section, source_unit)
        emit_success(ctx, "link remove-section", record, f"Removed {source_unit} from {doc} section {section}")

    _LINKS_IMPORT_MAP_FILE = typer.Option(None, "--file")

    @links_app.command("import-map")
    @handle_command_error("link import-map")
    def link_import_map(
        ctx: typer.Context,
        file_path: list[str] = _LINKS_IMPORT_MAP_FILE,
        directory: str | None = typer.Option(None, "--directory"),
        validate: bool = typer.Option(False, "--validate"),
        apply: bool = typer.Option(False, "--apply"),
        check_and_apply: bool = typer.Option(False, "--check-and-apply"),
        replace_section: bool = typer.Option(False, "--replace-section"),
    ) -> None:
        from documentledger.links import apply_mapping_batch, prepare_mapping_batch

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
        state = get_state(ctx)
        workspace = load_workspace(start=state.root)
        prepared = prepare_mapping_batch(workspace, mapping_paths)
        empty_paths = set(prepared.empty_mapping_paths)
        events = [
            {"event": "mapping_skipped_empty" if path in empty_paths else "mapping_validated", "file": path}
            for path in prepared.mapping_paths
        ]
        if validate:
            result = {
                "mapping_files": len(prepared.mapping_paths),
                "empty_mapping_files": prepared.empty_mapping_count,
                "documents": len(prepared.documents),
                "sections": prepared.section_count,
                "planned_edges": prepared.planned_edges,
                "applied": False,
            }
            emit_success(ctx, "link import-map", result, "Mapping validated.", events + _profile_events(ctx, "link import-map", started_at))
            return
        result = apply_mapping_batch(workspace, prepared, replace_sections=replace_section) | {"applied": True}
        for doc_path in sorted(prepared.documents):
            events.append({"event": "document_saved", "doc": doc_path})
        emit_success(
            ctx,
            "link import-map",
            result,
            "Mapping applied." if apply else "Mapping validated and applied.",
            events + _profile_events(ctx, "link import-map", started_at),
        )

    @links_app.command("audit")
    @handle_command_error("link audit")
    def link_audit(ctx: typer.Context) -> None:
        from documentledger.links import audit_links

        state = get_state(ctx)
        result = audit_links(load_workspace(start=state.root))
        if not result["ok"]:
            raise DocumentledgerError(
                "link_audit_failed",
                f"Link audit found {len(result['issues'])} issue(s).",
                ["Resolve the reported stale or missing links and rerun `documentledger --json link audit`."],
                details={"issues": result["issues"]},
            )
        emit_success(ctx, "link audit", result, "Link audit passed." if result["ok"] else "Link audit found issues.")

    @links_app.command("propose")
    @handle_command_error("link propose")
    def link_propose(
        ctx: typer.Context,
        all_docs: bool = typer.Option(False, "--all-docs"),
        out_dir: str | None = typer.Option(None, "--out-dir", "--out"),
        include_tests: bool = typer.Option(False, "--include-tests"),
    ) -> None:
        from documentledger.links import propose_mappings

        started_at = perf_counter()
        state = get_state(ctx)
        workspace = load_workspace(start=state.root)
        result, events = propose_mappings(workspace, all_docs=all_docs, out_dir=out_dir, include_tests=include_tests)
        emit_success(
            ctx,
            "link propose",
            result,
            f"Wrote {len(result['proposal_files'])} proposal files.",
            events + _profile_events(ctx, "link propose", started_at),
        )
