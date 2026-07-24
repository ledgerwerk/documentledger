from __future__ import annotations

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
    ) -> None:
        super().__init__(message, code=code)
        self.code = code
        self.message = message
        self.remediation = remediation or []
        self.exit_code = exit_code
