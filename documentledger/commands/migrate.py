"""Migrate commands: status, plan, apply, recover, cleanup."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import typer

from documentledger.cli_support import emit_success, get_state, handle_command_error
from documentledger.errors import DocumentledgerError
from documentledger.storage import load_workspace


def register_migrate_commands(app: typer.Typer, migrate_app: typer.Typer, storage_app: typer.Typer) -> None:
    """Register migrate commands and legacy storage compatibility wrappers."""

    @migrate_app.command("status")
    @handle_command_error("migrate status")
    def migrate_status(ctx: typer.Context) -> None:
        """Show migration status."""
        from documentledger.legacy import find_legacy_config
        from documentledger.project import resolve_canonical_project

        state = get_state(ctx)
        legacy_config = find_legacy_config(state.root)
        has_legacy = legacy_config is not None
        canonical_registered = False
        try:
            resolve_canonical_project(state.root, require_data=False)
            canonical_registered = True
        except DocumentledgerError:
            pass
        result: dict[str, Any] = {
            "legacy_config_detected": has_legacy,
            "legacy_data_detected": has_legacy,
            "canonical_registered": canonical_registered,
            "recommended_next": "migrate plan storage-layout" if has_legacy and canonical_registered else "init",
        }
        emit_success(ctx, "migrate status", result, "Migration status retrieved.")

    @migrate_app.command("plan")
    @handle_command_error("migrate plan")
    def migrate_plan(
        ctx: typer.Context,
        migration_name: str = typer.Argument("storage-layout"),
        output: str | None = typer.Option(None, "--output"),
        adopt_project_uuid: bool = typer.Option(False, "--adopt-project-uuid"),
        repair_missing_source_index: bool = typer.Option(False, "--repair-missing-source-index"),
        retain_unknown: bool = typer.Option(False, "--retain-unknown"),
        reject_unknown: bool = typer.Option(False, "--reject-unknown"),
    ) -> None:
        """Generate a migration plan without applying it."""
        from documentledger.migration import plan_migration, write_plan

        state = get_state(ctx)
        if migration_name != "storage-layout":
            raise DocumentledgerError("invalid_migration", f"Unknown migration: {migration_name}")
        plan = plan_migration(state.root, adopt_project_uuid=adopt_project_uuid)
        if output:
            target = Path(output)
            if str(target) == "-":
                import json
                import sys

                sys.stdout.write(json.dumps(plan.to_dict(), indent=2, sort_keys=True) + "\n")
            else:
                write_plan(target, plan)
        result = plan.to_dict() | {"dry_run": True, "activation": "manifest update last", "legacy_cleanup": "not included"}
        if output:
            result["output"] = str(output)
        emit_success(ctx, "migrate plan", result, f"Migration plan {plan.migration_id} is ready; no state was changed.")

    @migrate_app.command("apply")
    @handle_command_error("migrate apply")
    def migrate_apply(
        ctx: typer.Context,
        migration_name: str = typer.Argument("storage-layout"),
        plan_file: str | None = typer.Option(None, "--plan-file"),
        dry_run: bool = typer.Option(False, "--dry-run"),
        adopt_project_uuid: bool = typer.Option(False, "--adopt-project-uuid"),
        repair_missing_source_index: bool = typer.Option(False, "--repair-missing-source-index"),
    ) -> None:
        """Apply a validated migration plan."""
        import json

        from documentledger.migration import apply_migration, plan_migration

        state = get_state(ctx)
        if migration_name != "storage-layout":
            raise DocumentledgerError("invalid_migration", f"Unknown migration: {migration_name}")
        plan = plan_migration(state.root, adopt_project_uuid=adopt_project_uuid)
        if plan_file:
            target = Path(plan_file)
            if target.is_file():
                stored = json.loads(target.read_text(encoding="utf-8"))
                if stored.get("plan_sha256") != plan.plan_sha256:
                    raise DocumentledgerError(
                        "storage_migration_conflict", "The migration plan file is stale; rerun dry-run and review it again."
                    )
        if dry_run:
            result = plan.to_dict() | {"dry_run": True, "activation": "manifest update last", "legacy_cleanup": "not included"}
            emit_success(ctx, "migrate apply", result, f"Migration plan {plan.migration_id} is ready; no state was changed.")
            return
        result = apply_migration(plan, adopt_project_uuid=adopt_project_uuid, repair_missing_source_index=repair_missing_source_index)
        emit_success(ctx, "migrate apply", result, "Canonical Documentledger storage is active; legacy files were retained.")

    @migrate_app.command("recover")
    @handle_command_error("migrate recover")
    def migrate_recover(
        ctx: typer.Context,
        journal: str = typer.Option(..., "--journal"),
        policy: str = typer.Option("auto", "--policy"),
    ) -> None:
        """Recover from an interrupted migration."""
        from documentledger.migration import recover_migration

        state = get_state(ctx)
        result = recover_migration(state.root, journal_path=Path(journal), policy=policy)
        emit_success(ctx, "migrate recover", result, "Migration recovery completed.")

    @migrate_app.command("cleanup")
    @handle_command_error("migrate cleanup")
    def migrate_cleanup(
        ctx: typer.Context,
        migration_name: str = typer.Argument("storage-layout"),
        journal: str | None = typer.Option(None, "--journal"),
        dry_run: bool = typer.Option(False, "--dry-run"),
        yes: bool = typer.Option(False, "--yes"),
        discard_derived: bool = typer.Option(False, "--discard-derived"),
        remove_external_source: bool = typer.Option(False, "--remove-external-source"),
    ) -> None:
        """Clean up legacy source after migration."""
        from documentledger.migration import cleanup_legacy

        state = get_state(ctx)
        if migration_name != "storage-layout":
            raise DocumentledgerError("invalid_migration", f"Unknown migration: {migration_name}")
        result = cleanup_legacy(
            state.root, yes=yes, dry_run=dry_run, remove_external_source=remove_external_source, discard_derived=discard_derived
        )
        emit_success(
            ctx,
            "migrate cleanup",
            result,
            "Legacy cleanup completed." if not dry_run else "Legacy cleanup is safe to perform after review.",
        )

    # Legacy storage compatibility wrappers
    @storage_app.command("migrate")
    @handle_command_error("storage migrate")
    def storage_migrate(
        ctx: typer.Context,
        dry_run: bool = typer.Option(False, "--dry-run"),
        plan_file: str | None = typer.Option(None, "--plan-file"),
        adopt_project_uuid: bool = typer.Option(False, "--adopt-project-uuid"),
        repair_missing_source_index: bool = typer.Option(False, "--repair-missing-source-index"),
    ) -> None:
        """Legacy wrapper: use 'migrate plan storage-layout' or 'migrate apply storage-layout' instead."""
        from documentledger.cli_support import CLIWarning, get_state

        state = get_state(ctx)
        state = state.with_warning(CLIWarning(
            code="deprecated-command",
            message="'storage migrate' is deprecated. Use 'migrate plan storage-layout' or 'migrate apply storage-layout'.",
            replacement="migrate plan storage-layout" if dry_run else "migrate apply storage-layout",
        ))
        # Temporarily replace context state for the warning
        ctx.obj["state"] = state

        import json

        from documentledger.migration import apply_migration, plan_migration, write_plan

        plan = plan_migration(state.root, adopt_project_uuid=adopt_project_uuid)
        if plan_file:
            target = Path(plan_file)
            if dry_run:
                write_plan(target, plan)
            elif target.is_file():
                stored = json.loads(target.read_text(encoding="utf-8"))
                if stored.get("plan_sha256") != plan.plan_sha256:
                    raise DocumentledgerError(
                        "storage_migration_conflict", "The migration plan file is stale; rerun dry-run and review it again."
                    )
        if dry_run:
            result = plan.to_dict() | {"dry_run": True, "activation": "manifest update last", "legacy_cleanup": "not included"}
            emit_success(ctx, "storage migrate", result, f"Migration plan {plan.migration_id} is ready; no state was changed.")
            return
        result = apply_migration(plan, adopt_project_uuid=adopt_project_uuid, repair_missing_source_index=repair_missing_source_index)
        emit_success(ctx, "storage migrate", result, "Canonical Documentledger storage is active; legacy files were retained.")

    @storage_app.command("recover")
    @handle_command_error("storage recover")
    def storage_recover(ctx: typer.Context, journal: str = typer.Option(..., "--journal")) -> None:
        """Legacy wrapper: use 'migrate recover' instead."""
        from documentledger.cli_support import CLIWarning
        from documentledger.migration import recover_migration

        state = get_state(ctx)
        state = state.with_warning(CLIWarning(
            code="deprecated-command",
            message="'storage recover' is deprecated. Use 'migrate recover'.",
            replacement="migrate recover",
        ))
        ctx.obj["state"] = state

        result = recover_migration(state.root, journal_path=Path(journal), policy="auto")
        emit_success(ctx, "storage recover", result, "Migration recovery completed.")

    @storage_app.command("cleanup-legacy")
    @handle_command_error("storage cleanup-legacy")
    def storage_cleanup_legacy(
        ctx: typer.Context,
        yes: bool = typer.Option(False, "--yes"),
        dry_run: bool = typer.Option(False, "--dry-run"),
        remove_external_source: bool = typer.Option(False, "--remove-external-source"),
        discard_derived: bool = typer.Option(False, "--discard-derived"),
    ) -> None:
        """Legacy wrapper: use 'migrate cleanup storage-layout' instead."""
        from documentledger.cli_support import CLIWarning
        from documentledger.migration import cleanup_legacy

        state = get_state(ctx)
        state = state.with_warning(CLIWarning(
            code="deprecated-command",
            message="'storage cleanup-legacy' is deprecated. Use 'migrate cleanup storage-layout'.",
            replacement="migrate cleanup storage-layout",
        ))
        ctx.obj["state"] = state

        result = cleanup_legacy(
            state.root, yes=yes, dry_run=dry_run, remove_external_source=remove_external_source, discard_derived=discard_derived
        )
        emit_success(
            ctx,
            "storage cleanup-legacy",
            result,
            "Legacy cleanup completed." if not dry_run else "Legacy cleanup is safe to perform after review.",
        )

    @storage_app.command("verify")
    @handle_command_error("storage verify")
    def storage_verify(ctx: typer.Context, strict: bool = typer.Option(False, "--strict")) -> None:
        """Legacy wrapper: use 'storage validate' instead."""
        from documentledger.cli_support import CLIWarning
        from documentledger.migration import verify_canonical

        state = get_state(ctx)
        state = state.with_warning(CLIWarning(
            code="deprecated-command",
            message="'storage verify' is deprecated. Use 'storage validate'.",
            replacement="storage validate",
        ))
        ctx.obj["state"] = state

        result = verify_canonical(state.root, strict=strict)
        emit_success(ctx, "storage verify", result, "Canonical storage verification passed.")
