from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import yaml
from typer.testing import CliRunner

from documentledger.storage import load_workspace, normalize_doc_record, save_doc_record
from tests.conftest import invoke_json, invoke_json_may_fail, load_yaml, write_precision_sample


def _setup_linked_project(project: Path, runner: CliRunner, *, generated: bool = False) -> None:
    invoke_json(runner, ["init"])
    write_precision_sample(project)
    (project / "documentledger" / "overview.py").write_text("OVERVIEW = 'stable'\n", encoding="utf-8")
    invoke_json(runner, ["scan"])
    invoke_json(
        runner,
        [
            "link",
            "add-section",
            "--doc",
            "README.md",
            "--section",
            "docs",
            "--source-unit",
            "py:file:documentledger/overview.py",
            "--coverage",
            "broad-file-fallback",
            "--impact",
            "unknown",
            "--reason",
            "Maps the project overview.",
        ],
    )
    for section, source, coverage in (
        ("usage", "scan", "generated-reference" if generated else "cli-command"),
        ("usage-run-scan", "scan", "generated-reference" if generated else "cli-command"),
        ("usage-validate-ledger-state", "doctor", "cli-command"),
    ):
        invoke_json(
            runner,
            [
                "link",
                "add-section",
                "--doc",
                "docs/usage.md",
                "--section",
                section,
                "--source-unit",
                f"py:function:documentledger/cli.py::{source}",
                "--coverage",
                coverage,
                "--impact",
                "behavior",
                "--reason",
                f"Documents the {source} command.",
            ],
        )
    invoke_json(runner, ["scan"])
    invoke_json(runner, ["review"])


def _change_scan_signature(project: Path) -> None:
    path = project / "documentledger" / "cli.py"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "def scan(ctx: typer.Context) -> None:",
            "def scan(ctx: typer.Context, full: bool = False) -> None:",
        ),
        encoding="utf-8",
    )


def _record_path(project: Path) -> Path:
    return next((project / ".ledger" / "documentledger" / "data" / "docs").glob("*.yaml"))


def _section_freshness(project: Path, slug: str = "usage-run-scan") -> dict[str, object] | None:
    record = load_yaml(_record_path(project))
    section = next(section for section in record["sections"] if section["section_id"].endswith(f"::{slug}"))
    return section.get("freshness")


def test_finish_records_updated_after_source_and_section_edit(project: Path, runner: CliRunner) -> None:
    _setup_linked_project(project, runner)
    _change_scan_signature(project)
    doc = project / "docs" / "usage.md"
    doc.write_text(
        doc.read_text(encoding="utf-8").replace("Run `docledger scan`.", "Run `docledger scan` and inspect the result."),
        encoding="utf-8",
    )

    result = invoke_json(
        runner,
        [
            "finish",
            "--reviewed-no-change",
            "docs/usage.md#usage=Overview remains accurate.",
        ],
    )["result"]

    freshness = _section_freshness(project)
    assert freshness is not None
    assert freshness["disposition"] == "updated"
    assert freshness["source_scan_version"] == result["scan_version"]
    assert freshness["section_hash"]
    assert any(item["section_id"].endswith("::usage-run-scan") for item in result["freshness"])
    assert invoke_json(runner, ["document", "affected"])["result"]["affected_sections"] == []


def test_finish_requires_decision_for_unchanged_affected_section(project: Path, runner: CliRunner) -> None:
    _setup_linked_project(project, runner)
    _change_scan_signature(project)

    exit_code, result = invoke_json_may_fail(runner, ["finish"])

    assert exit_code != 0
    assert result["error"]["code"] == "freshness-decision-required"
    assert _section_freshness(project) is None


def test_finish_records_reviewed_no_change_reason(project: Path, runner: CliRunner) -> None:
    _setup_linked_project(project, runner)
    _change_scan_signature(project)

    invoke_json(
        runner,
        [
            "finish",
            "--reviewed-no-change",
            "docs/usage.md#usage=Overview remains accurate.",
            "--reviewed-no-change",
            "docs/usage.md#usage-run-scan=Behavior remains accurate.",
        ],
    )

    freshness = _section_freshness(project)
    assert freshness is not None
    assert freshness["disposition"] == "reviewed-no-change"
    assert freshness["reason"] == "Behavior remains accurate."


def test_finish_requires_and_records_generated_verification(project: Path, runner: CliRunner) -> None:
    _setup_linked_project(project, runner, generated=True)
    _change_scan_signature(project)

    exit_code, missing_decision = invoke_json_may_fail(runner, ["finish"])
    assert exit_code != 0
    assert missing_decision["error"]["code"] == "freshness-decision-required"
    assert _section_freshness(project) is None

    invoke_json(
        runner,
        [
            "finish",
            "--generated-verified",
            "docs/usage.md#usage=Generated reference verified.",
            "--generated-verified",
            "docs/usage.md#usage-run-scan=Generated reference verified.",
        ],
    )

    freshness = _section_freshness(project)
    assert freshness is not None
    assert freshness["disposition"] == "generated-verified"
    assert freshness["reason"] == "Generated reference verified."


def test_finish_validation_failure_does_not_record_freshness(project: Path, runner: CliRunner) -> None:
    _setup_linked_project(project, runner)
    _change_scan_signature(project)
    config = project / ".ledger" / "documentledger" / "config.toml"
    config.write_text(
        config.read_text(encoding="utf-8").replace("commands = []", "commands = [\"python -c 'import sys; sys.exit(3)'\"]"),
        encoding="utf-8",
    )

    exit_code, result = invoke_json_may_fail(
        runner,
        [
            "finish",
            "--reviewed-no-change",
            "docs/usage.md#usage=Overview remains accurate.",
            "--reviewed-no-change",
            "docs/usage.md#usage-run-scan=Behavior remains accurate.",
        ],
    )

    assert exit_code != 0
    assert result["error"]["code"] == "validation-command-failed"
    assert _section_freshness(project) is None


def test_finish_validation_retry_preserves_edited_section_baseline(project: Path, runner: CliRunner) -> None:
    _setup_linked_project(project, runner)
    _change_scan_signature(project)
    record = load_yaml(_record_path(project))
    section = next(item for item in record["sections"] if item["section_id"].endswith("::usage-run-scan"))
    original_hash = section["section_hash"]
    doc = project / "docs" / "usage.md"
    doc.write_text(
        doc.read_text(encoding="utf-8").replace("Run `docledger scan`.", "Run `docledger scan` and inspect the result."),
        encoding="utf-8",
    )
    config = project / ".ledger" / "documentledger" / "config.toml"
    config.write_text(
        config.read_text(encoding="utf-8").replace("commands = []", "commands = [\"python -c 'import sys; sys.exit(3)'\"]"),
        encoding="utf-8",
    )

    exit_code, result = invoke_json_may_fail(
        runner,
        ["finish", "--reviewed-no-change", "docs/usage.md#usage=Overview remains accurate."],
    )

    assert exit_code != 0
    assert result["error"]["code"] == "validation-command-failed"
    assert _section_freshness(project) is None
    failed_record = load_yaml(_record_path(project))
    failed_section = next(item for item in failed_record["sections"] if item["section_id"].endswith("::usage-run-scan"))
    assert failed_section["pending_section_hash"] == original_hash

    config.write_text(
        config.read_text(encoding="utf-8").replace(
            "commands = [\"python -c 'import sys; sys.exit(3)'\"]",
            "commands = []",
        ),
        encoding="utf-8",
    )
    invoke_json(runner, ["finish", "--reviewed-no-change", "docs/usage.md#usage=Overview remains accurate."])

    assert _section_freshness(project)["disposition"] == "updated"


def test_finish_creates_current_validation_attestation(project: Path, runner: CliRunner) -> None:
    _setup_linked_project(project, runner)
    _change_scan_signature(project)
    config = project / ".ledger" / "documentledger" / "config.toml"
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            "commands = []",
            "commands = [\"python -c 'import sys; sys.exit(0)'\"]",
        ),
        encoding="utf-8",
    )

    result = invoke_json(
        runner,
        [
            "finish",
            "--reviewed-no-change",
            "docs/usage.md#usage=Overview remains accurate.",
            "--reviewed-no-change",
            "docs/usage.md#usage-run-scan=Behavior remains accurate.",
        ],
    )["result"]
    documentation = invoke_json(runner, ["status"])["result"]["documentation"]

    assert result["state"] == "clean"
    assert len(result["validation"]) == 1
    assert documentation["validation_state"] == "passed_current"
    assert documentation["validation_verified_for_current_content"] is True


def test_finish_rejects_validation_that_mutates_docs(project: Path, runner: CliRunner) -> None:
    _setup_linked_project(project, runner)
    _change_scan_signature(project)
    (project / "mutate_docs.py").write_text(
        "from pathlib import Path\npath = Path('docs/usage.md')\npath.write_text(path.read_text() + 'mutated during validation')\n",
        encoding="utf-8",
    )
    config = project / ".ledger" / "documentledger" / "config.toml"
    config.write_text(
        config.read_text(encoding="utf-8").replace("commands = []", 'commands = ["python mutate_docs.py"]'),
        encoding="utf-8",
    )

    exit_code, result = invoke_json_may_fail(
        runner,
        [
            "finish",
            "--reviewed-no-change",
            "docs/usage.md#usage=Overview remains accurate.",
            "--reviewed-no-change",
            "docs/usage.md#usage-run-scan=Behavior remains accurate.",
        ],
    )
    documentation = invoke_json(runner, ["status"])["result"]["documentation"]

    assert exit_code != 0
    assert result["error"]["code"] == "validation-command-failed"
    assert _section_freshness(project) is None
    assert documentation["validation_state"] == "failed"
    assert documentation["validation_verified_for_current_content"] is False


def test_finish_link_audit_failure_does_not_record_freshness(project: Path, runner: CliRunner) -> None:
    _setup_linked_project(project, runner)
    (project / "documentledger" / "cli.py").unlink()
    invoke_json(runner, ["scan"])

    exit_code, result = invoke_json_may_fail(runner, ["finish"])

    assert exit_code != 0
    assert result["error"]["code"] == "link-audit-failed"
    assert _section_freshness(project) is None


def test_legacy_doc_record_upgrades_without_losing_links(project: Path, runner: CliRunner) -> None:
    _setup_linked_project(project, runner)
    path = _record_path(project)
    raw_record = load_yaml(path)
    links = deepcopy(raw_record["sections"][0]["links"])
    raw_record["schema"] = "documentledger.doc_record.v4"
    path.write_text(yaml.safe_dump(raw_record, sort_keys=False), encoding="utf-8")

    workspace = load_workspace(start=project)
    normalized = normalize_doc_record(workspace, raw_record)
    save_doc_record(workspace, raw_record)

    migrated = load_yaml(path)
    assert normalized["schema"] == "documentledger.doc_record.v5"
    assert migrated["schema"] == "documentledger.doc_record.v5"
    assert migrated["sections"][0]["links"] == links
