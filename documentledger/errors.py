from __future__ import annotations

from collections.abc import Mapping

from ledgercore.cli import CLIError, ExitCode
from ledgercore.errors import LedgerCoreError

STORAGE_ERROR_CODES = frozenset(
    {
        "storage_migration_required",
        "storage_layout_ambiguous",
        "storage_registration_conflict",
        "storage_binding_invalid",
        "storage_migration_conflict",
        "storage_migration_incomplete",
        "storage_migration_failed",
        "project_uuid_mismatch",
        "source_index_missing",
        "source_index_hash_mismatch",
        "source_index_repair_failed",
        "legacy_cleanup_unsafe",
        "unsupported_canonical_layout",
    }
)

# Map domain error codes to canonical exit codes.
_EXIT_CODE_MAP: dict[str, ExitCode] = {
    # Exit 2: CLI usage errors
    "invalid_path": ExitCode.USAGE,
    "invalid_cursor": ExitCode.USAGE,
    "invalid_option_combination": ExitCode.USAGE,
    "invalid_mapping_batch": ExitCode.USAGE,
    "invalid_selector": ExitCode.USAGE,
    "invalid_mapping": ExitCode.USAGE,
    "legacy_init_options_unsupported": ExitCode.USAGE,
    "doc_required": ExitCode.USAGE,
    "reason_required": ExitCode.USAGE,
    "unsupported_output_target": ExitCode.USAGE,
    "stdout_json_conflict": ExitCode.USAGE,
    # Exit 3: workspace/resource unavailable
    "workspace_not_found": ExitCode.UNAVAILABLE,
    "storage_missing": ExitCode.UNAVAILABLE,
    "legacy_workspace_not_found": ExitCode.UNAVAILABLE,
    "document_not_found": ExitCode.UNAVAILABLE,
    "source_not_found": ExitCode.UNAVAILABLE,
    "source_unit_not_found": ExitCode.UNAVAILABLE,
    "section_not_found": ExitCode.UNAVAILABLE,
    "scan_missing": ExitCode.UNAVAILABLE,
    "unlinked_doc": ExitCode.UNAVAILABLE,
    # Exit 4: conflict/safety precondition
    "already_initialized_conflict": ExitCode.CONFLICT,
    "storage_registration_conflict": ExitCode.CONFLICT,
    "storage_binding_invalid": ExitCode.CONFLICT,
    "storage_migration_conflict": ExitCode.CONFLICT,
    "storage_migration_incomplete": ExitCode.CONFLICT,
    "project_uuid_mismatch": ExitCode.CONFLICT,
    "source_index_hash_mismatch": ExitCode.CONFLICT,
    "legacy_cleanup_unsafe": ExitCode.CONFLICT,
    "unsupported_canonical_layout": ExitCode.CONFLICT,
    # Exit 5: external dependency
    "validation_subprocess_failed": ExitCode.EXTERNAL_FAILURE,
    "external_tool_failed": ExitCode.EXTERNAL_FAILURE,
    "link_audit_failed": ExitCode.DOMAIN_FAILURE,
    "check_failed": ExitCode.DOMAIN_FAILURE,
}


def exit_code_for(domain_code: str) -> ExitCode:
    """Map a domain error code to a canonical Ledgerwerk exit code."""
    return _EXIT_CODE_MAP.get(domain_code, ExitCode.DOMAIN_FAILURE)


def normalize_error_code(domain_code: str) -> str:
    """Normalize a domain error code to the canonical lowercase-hyphenated form."""
    return domain_code.lower().replace("_", "-")


class DocumentledgerError(LedgerCoreError):
    """Structured Documentledger error with a machine-readable code.

    This is a plain exception on purpose: the CLI layer owns error rendering so
    that command names and JSON-vs-human output stay consistent. It does not
    subclass ``click.ClickException`` because Click would intercept it and
    bypass that control.
    """

    def __init__(
        self,
        code: str,
        message: str,
        remediation: list[str] | None = None,
        exit_code: int = 1,
        details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message, code=code)
        self.code = code
        self.message = message
        self.remediation = remediation or []
        self.exit_code = exit_code
        self.details: Mapping[str, object] = details or {}


def to_cli_error(exc: DocumentledgerError) -> CLIError:
    """Translate a Documentledger domain error to a CLIError."""
    return CLIError(
        code=normalize_error_code(exc.code),
        message=exc.message,
        exit_code=exit_code_for(exc.code),
        remediation=tuple(exc.remediation),
        details={
            **exc.details,
            "domain_code": exc.code,
        },
    )
