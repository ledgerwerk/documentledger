"""Strict parsing and writing of Documentledger tool configuration."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ledgercore.atomic import atomic_write_text
from ledgercore.errors import LedgerCoreError

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback
    import tomli as tomllib  # type: ignore[no-redef]

from documentledger.errors import DocumentledgerError
from documentledger.models import ToolConfig

_TOP_LEVEL = {"config_version", "ledger", "scan", "validation", "policy"}
_LEDGER = {"code"}
_SCAN = {"source_roots", "doc_roots", "source_extensions", "doc_extensions"}
_VALIDATION = {"commands"}
_POLICY = {"require_doc_frontmatter"}


def _table(data: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    value = data.get(name, {})
    if not isinstance(value, Mapping):
        raise DocumentledgerError("invalid_tool_config", f"{name} must be a TOML table.")
    return value


def _unknown(data: Mapping[str, Any], allowed: set[str], name: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise DocumentledgerError(
            "unsupported_tool_config_field",
            f"{name} contains unsupported field(s): {', '.join(unknown)}.",
            ["Remove the unsupported fields or migrate the legacy configuration explicitly."],
        )


def _strings(value: Any, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise DocumentledgerError("invalid_tool_config", f"{name} must be an array of strings.")
    return tuple(value)


def parse_tool_config(data: Mapping[str, Any], *, path: Path | None = None) -> ToolConfig:
    """Parse config version 2 without accepting legacy routing fields."""
    _unknown(data, _TOP_LEVEL, "config")
    version = data.get("config_version")
    if version != 2 or isinstance(version, bool):
        raise DocumentledgerError(
            "unsupported_tool_config_version",
            f"{path or 'config'} must declare config_version = 2.",
            ["Run the explicit storage migration to transform legacy configuration."],
        )
    ledger = _table(data, "ledger")
    _unknown(ledger, _LEDGER, "ledger")
    code = ledger.get("code", "dl")
    if not isinstance(code, str) or not code:
        raise DocumentledgerError("invalid_tool_config", "ledger.code must be a non-empty string.")
    scan = _table(data, "scan")
    _unknown(scan, _SCAN, "scan")
    validation = _table(data, "validation")
    _unknown(validation, _VALIDATION, "validation")
    policy = _table(data, "policy")
    _unknown(policy, _POLICY, "policy")
    frontmatter = policy.get("require_doc_frontmatter", False)
    if not isinstance(frontmatter, bool):
        raise DocumentledgerError("invalid_tool_config", "policy.require_doc_frontmatter must be boolean.")
    return ToolConfig(
        config_version=2,
        ledger_code=code,
        source_roots=_strings(scan.get("source_roots", ()), "scan.source_roots"),
        doc_roots=_strings(scan.get("doc_roots", ()), "scan.doc_roots"),
        source_extensions=_strings(scan.get("source_extensions", ()), "scan.source_extensions"),
        doc_extensions=_strings(scan.get("doc_extensions", ()), "scan.doc_extensions"),
        validation_commands=_strings(validation.get("commands", ()), "validation.commands"),
        require_doc_frontmatter=frontmatter,
    )


def load_tool_config_v2(path: Path) -> ToolConfig:
    if path.is_symlink() or not path.is_file():
        raise DocumentledgerError("tool_config_missing", f"Canonical tool config is missing: {path}.")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DocumentledgerError("invalid_tool_config", f"Unable to read {path}: {exc}") from exc
    return parse_tool_config(data, path=path)


def tool_config_document(config: ToolConfig) -> str:
    """Render the stable schema-2 TOML representation."""
    lines = ["config_version = 2", "", "[ledger]", f'code = "{config.ledger_code}"', ""]
    lines.extend(
        [
            "[scan]",
            f"source_roots = {list(config.source_roots)!r}",
            f"doc_roots = {list(config.doc_roots)!r}",
            f"source_extensions = {list(config.source_extensions)!r}",
            f"doc_extensions = {list(config.doc_extensions)!r}",
            "",
            "[validation]",
            f"commands = {list(config.validation_commands)!r}",
            "",
            "[policy]",
            f"require_doc_frontmatter = {str(config.require_doc_frontmatter).lower()}",
            "",
        ]
    )
    # TOML accepts Python's single-quoted repr poorly; use a tiny JSON-like
    # string encoder for the array values.
    for key in ("source_roots", "doc_roots", "source_extensions", "doc_extensions", "commands"):
        pass
    import json

    text = "\n".join(lines)
    for key, values in (
        ("source_roots", config.source_roots),
        ("doc_roots", config.doc_roots),
        ("source_extensions", config.source_extensions),
        ("doc_extensions", config.doc_extensions),
        ("commands", config.validation_commands),
    ):
        text = text.replace(f"{key} = {list(values)!r}", f"{key} = {json.dumps(list(values))}")
    return text


def write_tool_config_v2(path: Path, config: ToolConfig) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(path, tool_config_document(config))
    except (OSError, LedgerCoreError) as exc:
        raise DocumentledgerError("tool_config_write_failed", f"Unable to write {path}: {exc}") from exc
