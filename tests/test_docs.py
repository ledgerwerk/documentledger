from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from documentledger.cli import app
from tests.conftest import assert_no_timestamp_keys, invoke_json, load_yaml, write_precision_sample


def test_docs_list_shows_known_docs(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    invoke_json(runner, ["scan"])
    data = invoke_json(runner, ["document", "list"])
    assert data["result"]["docs"] == ["README.md"]


def test_docs_stale_shows_latest_scan_stale(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    invoke_json(runner, ["link", "add", "--doc", "README.md", "--source", "documentledger/cli.py"])
    invoke_json(runner, ["scan"])
    (project / "documentledger" / "cli.py").write_text("changed\n", encoding="utf-8")
    invoke_json(runner, ["scan"])
    data = invoke_json(runner, ["document", "stale"])
    assert data["result"]["stale_docs"][0]["doc_path"] == "README.md"
    assert data["result"]["stale_docs"][0]["affected_sections"]


def test_mark_fresh_updates_fields(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    invoke_json(runner, ["link", "add", "--doc", "README.md", "--source", "documentledger/cli.py"])
    invoke_json(runner, ["scan"])
    (project / "documentledger" / "cli.py").write_text("changed\n", encoding="utf-8")
    scan_version = invoke_json(runner, ["scan"])["result"]["version"]
    data = invoke_json(
        runner, ["document", "mark-fresh", "--doc", "README.md", "--reason", f"Docs updated after scan version {scan_version}."]
    )
    record = load_yaml(next((project / ".ledger" / "documentledger" / "data" / "docs").glob("*.yaml")))
    storage = load_yaml(project / ".ledger" / "documentledger" / "data" / "storage.yaml")
    assert data["result"]["updated_docs"] == ["README.md"]
    assert record["schema"] == "documentledger.doc_record.v4"
    assert record["last_fresh_scan_version"] == scan_version
    assert record["version"] == storage["state_version"]
    assert_no_timestamp_keys(record)


def test_mark_fresh_noop_does_not_bump_version(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    invoke_json(runner, ["link", "add", "--doc", "README.md", "--source", "documentledger/cli.py"])
    invoke_json(runner, ["scan"])
    (project / "documentledger" / "cli.py").write_text("changed\n", encoding="utf-8")
    scan_version = invoke_json(runner, ["scan"])["result"]["version"]
    reason = f"Docs updated after scan version {scan_version}."
    invoke_json(runner, ["document", "mark-fresh", "--doc", "README.md", "--reason", reason])
    invoke_json(runner, ["document", "mark-fresh", "--doc", "README.md", "--reason", reason])
    record = load_yaml(next((project / ".ledger" / "documentledger" / "data" / "docs").glob("*.yaml")))
    storage = load_yaml(project / ".ledger" / "documentledger" / "data" / "storage.yaml")
    assert record["version"] == 5
    assert storage["state_version"] == 5


def test_mark_fresh_requires_reason(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    result = runner.invoke(app, ["--json", "document", "mark-fresh", "--doc", "README.md"])
    assert result.exit_code != 0


def test_docs_sections_and_affected_show_precise_section(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    write_precision_sample(project)
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
            "py:function:documentledger/cli.py::doctor",
            "--coverage",
            "cli-command",
            "--impact",
            "behavior",
            "--reason",
            "Documents the doctor command.",
        ],
    )
    sections = invoke_json(runner, ["document", "sections", "--doc", "docs/usage.md"])["result"]["docs"][0]["sections"]
    assert any(section["heading_slug"] == "usage-validate-ledger-state" for section in sections)
    invoke_json(runner, ["scan"])
    cli_path = project / "documentledger" / "cli.py"
    cli_path.write_text(
        cli_path.read_text(encoding="utf-8").replace(
            "def doctor(ctx: typer.Context) -> None:",
            'def doctor(ctx: typer.Context, json: bool = typer.Option(False, "--json")) -> None:',
        ),
        encoding="utf-8",
    )
    invoke_json(runner, ["scan"])
    affected = invoke_json(runner, ["document", "affected"])["result"]["affected_sections"]
    assert [item["heading_slug"] for item in affected] == ["usage-validate-ledger-state"]


def test_mark_fresh_section_clears_live_affectedness_without_new_scan(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    write_precision_sample(project)
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
            "py:function:documentledger/cli.py::doctor",
            "--coverage",
            "cli-command",
            "--impact",
            "behavior",
            "--reason",
            "Documents the doctor command.",
        ],
    )
    invoke_json(runner, ["scan"])
    cli_path = project / "documentledger" / "cli.py"
    cli_path.write_text(
        cli_path.read_text(encoding="utf-8").replace(
            "def doctor(ctx: typer.Context) -> None:",
            'def doctor(ctx: typer.Context, json: bool = typer.Option(False, "--json")) -> None:',
        ),
        encoding="utf-8",
    )
    invoke_json(runner, ["scan"])
    before = invoke_json(runner, ["document", "affected"])["result"]["affected_sections"]
    assert before
    update = invoke_json(
        runner,
        [
            "document",
            "mark-fresh",
            "--doc",
            "docs/usage.md",
            "--section",
            "usage-validate-ledger-state",
            "--reason",
            "Updated doctor section after scan version 2.",
        ],
    )["result"]
    after = invoke_json(runner, ["document", "affected"])["result"]["affected_sections"]
    assert update["updated_sections"] == ["docs/usage.md::usage-validate-ledger-state"]
    assert after == []
