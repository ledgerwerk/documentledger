from __future__ import annotations

import hashlib
import re
from pathlib import PurePosixPath

from documentledger.errors import DocumentledgerError


def format_scan_id(number: int) -> str:
    return f"scan-{number:04d}"


def normalize_repo_path(path: str) -> str:
    if not path or "\\" in path:
        raise DocumentledgerError("invalid_path", f"Invalid repo-relative POSIX path: {path}")
    pure = PurePosixPath(path)
    if pure.is_absolute() or any(part == ".." for part in pure.parts):
        raise DocumentledgerError("invalid_path", f"Path must be repo-relative: {path}")
    normalized = pure.as_posix()
    if normalized in {".", ""}:
        raise DocumentledgerError("invalid_path", f"Invalid repo-relative POSIX path: {path}")
    return normalized


def doc_record_filename(doc_path: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", doc_path).strip("-").lower() or "doc"
    digest = hashlib.sha256(doc_path.encode()).hexdigest()[:8]
    return f"{slug}-{digest}.yaml"
