"""Shared CLI boundary for Documentledger.

This module provides the unified Ledgerwerk CLI contract:
- CommonCLIState for immutable root/json/warning state
- Success and error envelope emitters
- Warning collection
- Exit code translation
- Command path normalization
"""

from __future__ import annotations

from typing import Any

import typer
from ledgercore.cli import (
    CLIError,
    CLIWarning,
    CommonCLIState,
    ErrorEnvelope,
    SuccessEnvelope,
)

from documentledger.errors import DocumentledgerError, to_cli_error

__all__ = (
    "CLIWarning",
    "get_state",
    "emit_success",
    "emit_error",
    "handle_command_error",
    "version_callback",
    "normalize_command_path",
)


def get_state(ctx: typer.Context) -> CommonCLIState:
    """Retrieve the CommonCLIState from the Typer context."""
    return ctx.obj["state"]


def emit_success(
    ctx: typer.Context,
    command: str,
    result: dict[str, Any] | None = None,
    human: str = "",
    events: list[dict[str, Any]] | None = None,
) -> None:
    """Emit a success response in JSON or human format."""
    state = get_state(ctx)
    envelope = SuccessEnvelope(
        tool=state.tool,
        command=command,
        result=result or {},
        events=tuple(events or []),
        warnings=state.warnings,
    )
    if state.json_output:
        typer.echo(envelope.to_json())
    else:
        if human:
            typer.echo(human)
        for warning in state.warnings:
            typer.echo(f"Warning: {warning.message}", err=True)


def emit_error(
    ctx: typer.Context,
    command: str,
    exc: DocumentledgerError | CLIError,
) -> None:
    """Emit an error response in JSON or human format."""
    state = get_state(ctx)
    if isinstance(exc, DocumentledgerError):
        cli_err = to_cli_error(exc)
    else:
        cli_err = exc
    envelope = ErrorEnvelope(
        tool=state.tool,
        command=command,
        error={
            "code": cli_err.code,
            "message": cli_err.message,
            "remediation": list(cli_err.remediation),
            "details": dict(cli_err.details or {}),
        },
        events=(),
        warnings=state.warnings,
    )
    if state.json_output:
        typer.echo(envelope.to_json())
    else:
        typer.echo(f"Error: {cli_err.message}", err=True)
        for hint in cli_err.remediation:
            typer.echo(f"  hint: {hint}", err=True)
        for warning in state.warnings:
            typer.echo(f"Warning: {warning.message}", err=True)


def handle_command_error(command: str) -> Any:
    """Decorator factory for command error handling with unified envelopes."""

    def decorator(func: Any) -> Any:
        import functools

        @functools.wraps(func)
        def wrapper(ctx: typer.Context, *args: Any, **kwargs: Any) -> Any:
            try:
                return func(ctx, *args, **kwargs)
            except DocumentledgerError as exc:
                cli_err = to_cli_error(exc)
                emit_error(ctx, command, exc)
                raise typer.Exit(code=int(cli_err.exit_code)) from exc
            except CLIError as exc:
                emit_error(ctx, command, exc)
                raise typer.Exit(code=int(exc.exit_code)) from exc

        return wrapper

    return decorator


def version_callback(value: bool) -> None:
    """Print version and exit."""
    if value:
        from documentledger._version import version

        typer.echo(f"documentledger {version}")
        raise typer.Exit()


def normalize_command_path(path: str) -> str:
    """Normalize a command path to canonical form."""
    return " ".join(path.split())
