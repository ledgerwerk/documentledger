"""Source commands: list, show."""
from __future__ import annotations

from typing import Any

import typer

from documentledger.cli_support import emit_success, get_state, handle_command_error
from documentledger.errors import DocumentledgerError
from documentledger.identity import normalize_repo_path
from documentledger.storage import load_workspace
from documentledger.storage import coerce_int


def _normalize_cursor(cursor: str | None) -> int:
    if cursor is None:
        return 0
    try:
        value = int(cursor)
    except ValueError as exc:
        raise DocumentledgerError("invalid_cursor", f"Invalid cursor: {cursor}") from exc
    if value < 0:
        raise DocumentledgerError("invalid_cursor", f"Invalid cursor: {cursor}")
    return value


def _trim_source_record(unit: dict[str, Any], *, include_hashes: bool) -> dict[str, Any]:
    trimmed = dict(unit)
    if not include_hashes:
        trimmed.pop("hashes", None)
    return trimmed


def register_source_commands(app: typer.Typer, sources_app: typer.Typer) -> None:
    """Register source commands on the sources app."""

    _SOURCES_LIST_KIND = typer.Option(None, "--kind")

    @sources_app.command("list")
    @handle_command_error("source list")
    def source_list(
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
        from time import perf_counter

        from documentledger.links import current_source_inventory

        started_at = perf_counter()
        kind = kind or []
        state = get_state(ctx)
        workspace = load_workspace(start=state.root)
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
        profile = [{"event": "profile", "operation": "source list", "elapsed_ms": round((perf_counter() - started_at) * 1000, 3)}]
        emit_success(ctx, "source list", result, human, profile)

    @sources_app.command("show")
    @handle_command_error("source show")
    def source_show(ctx: typer.Context, source_id: str = typer.Argument(...)) -> None:
        from documentledger.links import current_source_inventory

        state = get_state(ctx)
        inventory = current_source_inventory(load_workspace(start=state.root))
        if source_id not in inventory:
            raise DocumentledgerError("source_unit_not_found", f"Unknown source unit: {source_id}")
        emit_success(ctx, "source show", inventory[source_id], source_id)
