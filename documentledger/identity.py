from __future__ import annotations

from ledgercore.errors import PathValidationError
from ledgercore.hashing import sha256_text
from ledgercore.ids import NumericIdFormat, slugify_ref
from ledgercore.paths import validate_relative_posix_path

from documentledger.errors import DocumentledgerError

SCAN_ID_FORMAT = NumericIdFormat(prefix="scan", separator="-", width=4)


def format_scan_id(number: int) -> str:
    return SCAN_ID_FORMAT.format(number)


def normalize_repo_path(path: str) -> str:
    try:
        return validate_relative_posix_path(path, field_name="path")
    except PathValidationError as exc:
        raise DocumentledgerError("invalid_path", f"Invalid repo-relative POSIX path: {path}") from exc


def doc_record_filename(doc_path: str) -> str:
    slug = slugify_ref(doc_path, empty="doc")
    digest = sha256_text(doc_path)[:8]
    return f"{slug}-{digest}.yaml"
