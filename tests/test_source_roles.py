from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from documentledger.source_roles import classify_source_role
from tests.conftest import invoke_json, write_precision_sample


@pytest.mark.parametrize(
    ("unit", "expected"),
    [
        ("package/api.py", "production"),
        ("tests/test_api.py", "test"),
        ("test_api.py", "test"),
        ("package/api_test.py", "test"),
        ("package/generated/schema.py", "generated"),
        ("scripts/docs/build.py", "documentation-support"),
        ("package/internal/helper.py", "private"),
        ({"path": "package/api.py", "kind": "function", "qualname": "_helper"}, "private"),
        ({"path": "data/schema.json", "kind": "file"}, "unknown"),
    ],
)
def test_classifies_source_roles(unit: str | dict[str, str], expected: str) -> None:
    assert classify_source_role(unit) == expected


def _link_production_section(project: Path, runner: CliRunner) -> None:
    write_precision_sample(project)
    (project / "documentledger" / "api.py").write_text("def do_thing():\n    return 1\n", encoding="utf-8")
    invoke_json(
        runner,
        [
            "link",
            "add-section",
            "--doc",
            "docs/usage.md",
            "--section",
            "usage-validate-ledger-state",
            "--source-unit",
            "py:function:documentledger/api.py::do_thing",
            "--coverage",
            "api-autodoc",
            "--impact",
            "public-api",
            "--reason",
            "Documents the public API.",
        ],
    )
    invoke_json(runner, ["scan"])


def test_unmapped_test_changes_do_not_require_mapping_by_default(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    _link_production_section(project, runner)
    tests_dir = project / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_behavior.py").write_text("def behavior_check():\n    return True\n", encoding="utf-8")

    scan = invoke_json(runner, ["scan"])["result"]
    status = invoke_json(runner, ["status"])["result"]

    assert scan["unlinked_changed_sources"] == ["tests/test_behavior.py"]
    assert status["mapping_state"] == "complete"
    assert status["coverage_review_required"] is False
    assert status["ignored_change_counts"]["test"] >= 1


def test_production_unmapped_change_still_requires_mapping_review(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    _link_production_section(project, runner)
    (project / "documentledger" / "unmapped.py").write_text("value = 2\n", encoding="utf-8")

    invoke_json(runner, ["scan"])
    status = invoke_json(runner, ["status"])["result"]

    assert status["mapping_state"] == "review_required"
    assert status["relevant_unmapped_changed_unit_count"] > 0


def test_explicit_test_link_still_affects_documentation(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    write_precision_sample(project)
    tests_dir = project / "tests"
    tests_dir.mkdir()
    test_source = tests_dir / "test_behavior.py"
    test_source.write_text("def behavior_check():\n    return True\n", encoding="utf-8")
    invoke_json(
        runner,
        [
            "link",
            "add-section",
            "--doc",
            "docs/usage.md",
            "--section",
            "usage-validate-ledger-state",
            "--source-unit",
            "py:function:tests/test_behavior.py::behavior_check",
            "--coverage",
            "implementation-note",
            "--impact",
            "implementation-note",
            "--reason",
            "Documents an explicitly mapped test contract.",
        ],
    )
    invoke_json(runner, ["scan"])
    test_source.write_text("def behavior_check():\n    return False\n", encoding="utf-8")

    scan = invoke_json(runner, ["scan"])["result"]

    assert scan["stale_docs"] == ["docs/usage.md"]
    assert scan["affected_sections"][0]["changed_units"][0]["source_id"] == ("py:function:tests/test_behavior.py::behavior_check")


def test_config_can_opt_tests_into_mapping_review(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    _link_production_section(project, runner)
    config_path = project / ".ledger" / "documentledger" / "config.toml"
    config = config_path.read_text(encoding="utf-8")
    config_path.write_text(
        config.replace('mapping_review_roles = ["production"]', 'mapping_review_roles = ["production", "test"]'),
        encoding="utf-8",
    )
    tests_dir = project / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_behavior.py").write_text("def behavior_check():\n    return True\n", encoding="utf-8")

    invoke_json(runner, ["scan"])
    status = invoke_json(runner, ["status"])["result"]

    assert status["mapping_state"] == "review_required"
    assert status["relevant_unmapped_changed_unit_count"] > 0
