from __future__ import annotations

from pathlib import Path

from documentledger.cli import app
from tests.conftest import invoke_json, write_precision_sample


def prepare_stale_section(project: Path, runner) -> None:
    invoke_json(runner, ["init"])
    write_precision_sample(project)
    invoke_json(
        runner,
        [
            "links",
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


def test_build_context_affected_mode(project: Path, runner) -> None:
    prepare_stale_section(project, runner)
    data = invoke_json(runner, ["docs", "build-context", "--affected"])
    assert data["result"]["mode"] == "affected"
    assert data["result"]["sections"] == 1


def test_build_context_doc_mode_and_section_selector(project: Path, runner) -> None:
    invoke_json(runner, ["init"])
    write_precision_sample(project)
    data = invoke_json(runner, ["docs", "build-context", "--doc", "docs/usage.md", "--section", "usage-run-scan"])
    assert data["result"]["mode"] == "doc"
    assert data["result"]["sections"] == 1


def test_build_context_bootstrap_mode(project: Path, runner) -> None:
    invoke_json(runner, ["init"])
    invoke_json(runner, ["scan"])
    data = invoke_json(runner, ["docs", "build-context", "--bootstrap"])
    assert data["result"]["mode"] == "bootstrap"
    assert data["result"]["path"]


def test_build_context_requires_doc_for_section(project: Path, runner) -> None:
    invoke_json(runner, ["init"])
    result = runner.invoke(app, ["--json", "docs", "build-context", "--section", "usage-run-scan"])
    assert result.exit_code != 0
    assert "doc_required" in result.output


def test_build_context_reports_truncation(project: Path, runner) -> None:
    prepare_stale_section(project, runner)
    data = invoke_json(runner, ["docs", "build-context", "--affected", "--max-bytes", "500"])
    assert data["result"]["truncated"] is True
