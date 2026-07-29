"""Storage commands: where, validate."""

from __future__ import annotations

import typer

from documentledger.cli_support import emit_success, get_state, handle_command_error
from documentledger.errors import DocumentledgerError


def register_storage_commands(app: typer.Typer, storage_app: typer.Typer) -> None:
    """Register storage commands on the storage app."""

    @storage_app.command("where")
    @handle_command_error("storage where")
    def storage_where(ctx: typer.Context) -> None:
        from documentledger.legacy import find_legacy_config, load_legacy_project
        from documentledger.project import resolve_canonical_project

        state = get_state(ctx)
        manifest_exists = any(
            (parent / ".ledger" / "ledger.toml").is_file() for parent in [state.root.resolve(), *state.root.resolve().parents]
        )
        try:
            canonical = resolve_canonical_project(state.root, require_data=False)
        except DocumentledgerError:
            if manifest_exists:
                raise
            canonical = None
        if canonical is not None:
            paths = canonical.paths
            legacy_path = find_legacy_config(paths.project_root)
            result = {
                "layout": "canonical",
                "project_root": str(paths.project_root),
                "manifest_path": str(paths.manifest_path),
                "config_path": str(paths.config_path),
                "data_dir": str(paths.data_dir),
                "artifacts_dir": str(paths.artifacts_dir) if paths.artifacts_dir else None,
                "project_uuid": canonical.project_uuid,
                "storage_bindings_valid": True,
                "legacy_config": str(legacy_path) if legacy_path else None,
            }
            emit_success(ctx, "storage where", result, f"Canonical Documentledger storage: {paths.data_dir}")
            return
        legacy_path = find_legacy_config(state.root)
        if legacy_path is None:
            emit_success(ctx, "storage where", {"layout": "uninitialized"}, "Documentledger storage is uninitialized.")
            return
        legacy = load_legacy_project(legacy_path)
        result = {
            "layout": "legacy",
            "project_root": str(legacy.root),
            "config_path": str(legacy.config_path),
            "data_dir": str(legacy.data_dir),
            "artifacts_dir": None,
            "project_uuid": legacy.config.project_uuid,
        }
        emit_success(ctx, "storage where", result, f"Legacy Documentledger storage: {legacy.data_dir}")

    @storage_app.command("validate")
    @handle_command_error("storage validate")
    def storage_validate(ctx: typer.Context, strict: bool = typer.Option(False, "--strict")) -> None:
        from documentledger.migration import verify_canonical

        state = get_state(ctx)
        result = verify_canonical(state.root, strict=strict)
        emit_success(ctx, "storage validate", result, "Canonical storage verification passed.")
