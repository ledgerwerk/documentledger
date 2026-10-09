"""Safe, actionable error translation for user-selected output files."""

from __future__ import annotations

import errno as errno_module
from collections.abc import Callable
from pathlib import Path
from typing import NoReturn

from ledgercore.errors import LedgerCoreError

from documentledger.errors import DocumentledgerError


def output_write_error(
    path: Path,
    *,
    command: str,
    cause: BaseException,
    managed_artifact: bool,
) -> DocumentledgerError:
    """Build a structured output error without leaking exception tracebacks."""
    root_cause = cause
    while root_cause.__cause__ is not None:
        root_cause = root_cause.__cause__

    if managed_artifact:
        message = f"Unable to write {command} output to the configured artifacts mount."
        remediation = [
            "Check the configured ledgercore artifacts mount and its write permissions.",
            "Choose a writable explicit output path instead.",
        ]
        if command == "document build-context":
            remediation.append("Use --out - to stream raw Markdown to stdout (do not combine with --json).")
        else:
            remediation.append("Use --out-dir to select another writable proposal directory.")
    else:
        message = f"Unable to write {command} output to the requested path {path}."
        remediation = [
            "Choose a writable output path.",
            "Do not use an explicit output target that the current environment cannot write.",
        ]
        if command == "document build-context":
            remediation.extend(
                [
                    "Omit --out to use the configured artifacts store.",
                    "Use --out - to stream raw Markdown to stdout (do not combine with --json).",
                ]
            )
        else:
            remediation.append("Omit --out-dir to use the configured artifacts store.")

    root_errno = root_cause.errno if isinstance(root_cause, OSError) else None
    details: dict[str, object] = {
        "requested_path": str(path),
        "parent_directory": str(path.parent),
        "exception_category": type(cause).__name__,
        "root_cause_category": type(root_cause).__name__,
        "errno": root_errno,
        "errno_name": errno_module.errorcode.get(root_errno) if root_errno is not None else None,
        "output_location": "configured_artifacts_mount" if managed_artifact else "explicit_path",
    }
    return DocumentledgerError(
        "output_write_failed",
        message,
        remediation,
        details=details,
    )


def raise_output_write_error(
    path: Path,
    *,
    command: str,
    cause: BaseException,
    managed_artifact: bool,
) -> NoReturn:
    """Raise the normalized output error while preserving exception chaining."""
    raise output_write_error(path, command=command, cause=cause, managed_artifact=managed_artifact) from cause


def write_output_file(
    path: Path,
    writer: Callable[[Path], None],
    *,
    command: str,
    managed_artifact: bool,
) -> None:
    """Create a parent and write atomically, translating filesystem failures."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        writer(path)
    except (OSError, LedgerCoreError) as exc:
        raise_output_write_error(path, command=command, cause=exc, managed_artifact=managed_artifact)
