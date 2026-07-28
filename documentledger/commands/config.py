"""Config commands: show, validate."""
from __future__ import annotations

from typing import Any

import typer

from documentledger.cli_support import emit_success, get_state, handle_command_error
from documentledger.storage import load_workspace


def register_config_commands(app: typer.Typer, config_app: typer.Typer) -> None:
    """Register config commands on the config app."""

    @config_app.command("show")
    @handle_command_error("config show")
    def config_show(ctx: typer.Context) -> None:
        """Show effective Documentledger configuration."""
        state = get_state(ctx)
        workspace = load_workspace(start=state.root)
        result: dict[str, Any] = {
            "config_path": str(workspace.config.path),
            "project_name": workspace.config.project_name,
            "project_uuid": workspace.config.project_uuid,
            "source_roots": list(workspace.config.source_roots),
            "doc_roots": list(workspace.config.doc_roots),
            "source_extensions": list(workspace.config.source_extensions),
            "doc_extensions": list(workspace.config.doc_extensions),
            "validation_commands": list(workspace.config.validation_commands),
            "require_doc_frontmatter": workspace.config.require_doc_frontmatter,
        }
        paths = getattr(workspace, "paths", None)
        if paths is not None:
            result["layout_source"] = paths.layout_source
            result["manifest_path"] = str(paths.manifest_path)
            result["data_dir"] = str(paths.data_dir)
            result["artifacts_dir"] = str(paths.artifacts_dir) if paths.artifacts_dir else None
        emit_success(ctx, "config show", result, "Configuration retrieved.")

    @config_app.command("validate")
    @handle_command_error("config validate")
    def config_validate(ctx: typer.Context) -> None:
        """Validate the effective tool config without changing files."""
        state = get_state(ctx)
        workspace = load_workspace(start=state.root)
        issues: list[dict[str, str]] = []
        # Validate source roots exist
        for root_text in workspace.config.source_roots:
            path = workspace.config.root / root_text
            if not path.exists():
                issues.append({"code": "missing_source_root", "message": f"Source root does not exist: {root_text}"})
        # Validate doc roots exist
        for root_text in workspace.config.doc_roots:
            path = workspace.config.root / root_text
            if not path.exists():
                issues.append({"code": "missing_doc_root", "message": f"Doc root does not exist: {root_text}"})
        result = {"ok": not issues, "issues": issues}
        human = "Config validation passed." if not issues else f"Config validation found {len(issues)} issue(s)."
        emit_success(ctx, "config validate", result, human)
