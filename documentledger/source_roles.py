from __future__ import annotations

from pathlib import Path
from typing import Any

SOURCE_ROLES = frozenset({"production", "test", "private", "generated", "documentation-support", "unknown"})
DEFAULT_MAPPING_REVIEW_ROLES = ("production",)


def classify_source_role(unit: dict[str, Any] | str) -> str:
    if isinstance(unit, dict):
        path = str(unit.get("path", ""))
        qualname = str(unit.get("qualname", ""))
        kind = str(unit.get("kind", ""))
    else:
        path = unit
        qualname = ""
        kind = ""

    normalized = path.replace("\\", "/")
    parts = [part.lower() for part in normalized.split("/") if part]
    filename = Path(normalized).name.lower()
    if "tests" in parts or "test" in parts or filename.startswith("test_") or filename.endswith("_test.py"):
        return "test"
    if any(part in {"generated", "_generated", "gen"} for part in parts):
        return "generated"
    if any(
        part
        in {
            "docs_support",
            "documentation_support",
            "doc_tools",
            "docs_tools",
            "doc_tooling",
        }
        for part in parts
    ) or parts[:2] in (["scripts", "docs"], ["scripts", "documentation"]):
        return "documentation-support"
    if any(part in {"private", "internal"} or part.startswith("_") for part in parts):
        return "private"
    if any(part.startswith("_") for part in qualname.split(".")):
        return "private"
    if kind == "file" and Path(filename).suffix != ".py":
        return "unknown"
    if not normalized:
        return "unknown"
    return "production"


def mapping_review_roles(workspace: Any) -> frozenset[str]:
    configured = getattr(workspace.config, "mapping_review_roles", DEFAULT_MAPPING_REVIEW_ROLES)
    return frozenset(configured)
