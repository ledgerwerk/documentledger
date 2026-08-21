"""Deterministic contracts for the authored and generated documentation."""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback
    import tomli as tomllib  # type: ignore[no-redef]

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"


def _markdown_files() -> list[Path]:
    return sorted(path for path in DOCS.rglob("*.md") if "_build" not in path.parts and "venv" not in path.parts and path.name != "api.md")


def _requirement_pairs(path: Path) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        match = re.match(r"([A-Za-z0-9_.-]+)(.*)$", line)
        assert match, f"unparseable requirement: {raw!r}"
        pairs.add((match.group(1).lower().replace("_", "-"), match.group(2)))
    return pairs


def test_documentation_requirements_match_project_extra() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project_requirements = set(project["project"]["optional-dependencies"]["docs"])
    assert _requirement_pairs(DOCS / "requirements.txt") == {
        (
            re.match(r"([A-Za-z0-9_.-]+)", item).group(1).lower().replace("_", "-"),
            item[len(re.match(r"([A-Za-z0-9_.-]+)", item).group(1)) :],
        )
        for item in project_requirements
    }


def test_cli_reference_covers_catalog_exactly_once() -> None:
    from documentledger.command_catalog import COMMAND_INVENTORY

    text = (DOCS / "cli.md").read_text(encoding="utf-8")
    for entry in COMMAND_INVENTORY.entries:
        assert len(re.findall(rf"^## {re.escape(entry.path)}$", text, flags=re.MULTILINE)) == 1
        for alias in entry.aliases:
            assert f"`{alias}`" in text
    assert "## Compatibility commands" in text
    assert "These wrappers remain" in text


def test_cli_generator_normalizes_legacy_click_type_names() -> None:
    from scripts.generate_cli_reference import _canonical_type_name

    assert _canonical_type_name("text") == "str"
    assert _canonical_type_name("integer") == "int"
    assert _canonical_type_name("boolean") == "boolean"


def test_canonical_command_registration_matches_catalog() -> None:
    from typer.main import get_command

    from documentledger.cli import app
    from documentledger.command_catalog import COMMAND_INVENTORY

    command = get_command(app)
    registered: set[str] = set()

    def visit(current: object, prefix: str = "") -> None:
        commands = getattr(current, "commands", None)
        if not commands:
            if prefix not in {"mark-fresh"} and not prefix.startswith(
                ("docs ", "sources ", "links ", "storage migrate", "storage recover", "storage cleanup-legacy", "storage verify")
            ):
                registered.add(prefix)
            return
        for name, child in commands.items():
            visit(child, f"{prefix} {name}".strip())

    visit(command)
    assert registered == {entry.path for entry in COMMAND_INVENTORY.entries}


def test_deprecated_syntax_is_confined_to_compatibility_guidance() -> None:
    for path in (ROOT / "README.md", ROOT / "skills" / "documentledger" / "SKILL.md"):
        text = path.read_text(encoding="utf-8")
        assert "Compatibility" in text or "deprecated" in text
        assert "documentledger" in text
    assert "documentledger" in (DOCS / "usage.md").read_text(encoding="utf-8")
    assert not re.search(r":::\{deprecated\}\s*$", (DOCS / "usage.md").read_text(encoding="utf-8"), flags=re.MULTILINE)


def _toctree_entries(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    entries: list[str] = []
    in_tree = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```{toctree}"):
            in_tree = True
            continue
        if in_tree and stripped == "```":
            in_tree = not in_tree
            continue
        if not in_tree or stripped.startswith(":") or not stripped:
            continue
        entries.append(stripped)
    return entries


def test_published_markdown_is_reachable_from_root_toctrees() -> None:
    reachable: set[Path] = set()
    pending = [DOCS / "index.md"]
    while pending:
        current = pending.pop()
        if current in reachable:
            continue
        reachable.add(current)
        for entry in _toctree_entries(current):
            target = (current.parent / entry).with_suffix(".md")
            if target.exists() and target not in reachable:
                pending.append(target)
    expected = set(_markdown_files())
    assert expected <= reachable


def test_section_markers_are_unique_and_precede_h2() -> None:
    marker_locations: dict[str, Path] = {}
    for path in _markdown_files():
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            match = re.fullmatch(r"<!-- docledger-section: ([a-z0-9]+(?:-[a-z0-9]+)*) -->", line)
            if not match:
                continue
            marker = match.group(1)
            assert marker not in marker_locations, f"duplicate marker {marker}"
            marker_locations[marker] = path
            assert any(lines[next_index].startswith("## ") for next_index in range(index + 1, min(index + 3, len(lines))))


def test_local_markdown_links_resolve() -> None:
    link_pattern = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
    for path in _markdown_files() + [ROOT / "README.md"]:
        for target in link_pattern.findall(path.read_text(encoding="utf-8")):
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            local = target.split("#", 1)[0]
            assert (path.parent / local).exists(), f"{path}: missing link target {target}"


@pytest.mark.parametrize(
    "module",
    [
        "documentledger.project",
        "documentledger.config",
        "documentledger.models",
        "documentledger.storage",
        "documentledger.scanner",
        "documentledger.doc_index",
        "documentledger.source_index",
        "documentledger.links",
        "documentledger.identity",
        "documentledger.impact",
        "documentledger.render",
        "documentledger.migration",
        "documentledger.legacy",
        "documentledger.errors",
        "documentledger.cli",
        "documentledger.cli_support",
        "documentledger.command_catalog",
        "documentledger.launcher",
    ],
)
def test_api_modules_import(module: str) -> None:
    importlib.import_module(module)


def test_strict_build_and_generated_changelog_contracts() -> None:
    assert "-W --keep-going" in (DOCS / "build.sh").read_text(encoding="utf-8")
    changelog = (DOCS / "changelog.md").read_text(encoding="utf-8")
    assert "Generated by releaseledger" in changelog
    assert "<!-- generated by releaseledger -->" in changelog
    assert "<!-- releaseledger:generated-file -->" in changelog
