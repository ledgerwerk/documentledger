"""Link commands: list, add, remove, add-section, remove-section, import-map, audit, propose."""
from __future__ import annotations

from pathlib import Path
from time import perf_counter
from typing import Any

import typer
from ledgercore.yamlio import write_yaml as core_write_yaml

from documentledger.cli_support import emit_success, get_state, handle_command_error
from documentledger.errors import DocumentledgerError
from documentledger.storage import load_workspace


def _profile_events(ctx: typer.Context, operation: str, started_at: float) -> list[dict[str, Any]]:
    state = get_state(ctx)
    if not state.json_output:
        return []
    return [{"event": "profile", "operation": operation, "elapsed_ms": round((perf_counter() - started_at) * 1000, 3)}]


def register_link_commands(app: typer.Typer, links_app: typer.Typer) -> None:
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
        events = [{"event": "mapping_validated", "file": path} for path in prepared.mapping_paths]
        if validate:
            result = {
                "mapping_files": len(prepared.mapping_paths),
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
        emit_success(ctx, "link audit", result, "Link audit passed." if result["ok"] else "Link audit found issues.")

    @links_app.command("propose")
    @handle_command_error("link propose")
    def link_propose(
        ctx: typer.Context,
        all_docs: bool = typer.Option(False, "--all-docs"),
        out_dir: str | None = typer.Option(None, "--out-dir"),
    ) -> None:
        from documentledger.doc_index import doc_sections_for_file
        from documentledger.links import current_source_inventory
        from documentledger.scanner import collect_files

        started_at = perf_counter()
        if not all_docs:
            raise DocumentledgerError("invalid_selector", "Use --all-docs for proposal generation.")
        state = get_state(ctx)
        workspace = load_workspace(start=state.root)
        inventory = current_source_inventory(workspace)
        docs = collect_files(workspace, workspace.config.doc_roots, workspace.config.doc_extensions)
        artifacts_dir = getattr(getattr(workspace, "paths", None), "artifacts_dir", None)
        output_dir = (
            Path(out_dir) if out_dir else ((artifacts_dir / "proposals") if artifacts_dir else workspace.config.storage_dir / "proposals")
        )
        if (
            out_dir is None
            and artifacts_dir is not None
            and getattr(workspace.paths, "layout_source", "legacy") == "canonical"
            and not artifacts_dir.exists()
        ):
            import ledgercore

            from documentledger.project import resolve_canonical_project

            canonical = resolve_canonical_project(workspace.paths.project_root, require_data=True)
            ledgercore.initialize_storage_binding(canonical.layout.mounts["artifacts"], require_empty=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        written_files: list[str] = []
        proposed_sections = 0
        proposed_edges = 0
        events: list[dict[str, Any]] = []

        def _proposal_links_for_text(section_text: str, inventory: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
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

        for doc_path in docs:
            sections_payload: list[dict[str, Any]] = []
            for section in doc_sections_for_file(workspace.config.root / doc_path, doc_path):
                links = _proposal_links_for_text(section.text, inventory)
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
        emit_success(
            ctx,
            "link propose",
            result,
            f"Wrote {len(written_files)} proposal files.",
            events + _profile_events(ctx, "link propose", started_at),
        )
