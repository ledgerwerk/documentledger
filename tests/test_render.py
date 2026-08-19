from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from tests.conftest import invoke_json, write_precision_sample


def make_stale(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    config = project / ".ledger" / "documentledger" / "config.toml"
    config.write_text(
        config.read_text().replace("commands = []", 'commands = ["python -m pytest -q"]'),
        encoding="utf-8",
    )
    (project / "documentledger" / "old.py").write_text("old\n", encoding="utf-8")
    invoke_json(runner, ["links", "add", "--doc", "README.md", "--source", "documentledger/cli.py"])
    invoke_json(runner, ["links", "add", "--doc", "README.md", "--source", "documentledger/old.py"])
    invoke_json(runner, ["scan"])
    (project / "documentledger" / "cli.py").write_text("changed\n", encoding="utf-8")
    (project / "documentledger" / "old.py").unlink()
    (project / "documentledger" / "unlinked.py").write_text("new\n", encoding="utf-8")
    invoke_json(runner, ["scan"])


def test_context_includes_expected_sections(project: Path, runner: CliRunner) -> None:
    make_stale(project, runner)
    result = runner.invoke(__import__("documentledger.cli").cli.app, ["docs", "build-context", "--all", "--print"])
    assert result.exit_code == 0
    text = result.output
    assert "README.md" in text
    assert "documentledger/cli.py" in text
    assert "documentledger/old.py" in text
    assert "documentledger/unlinked.py" in text
    assert "python -m pytest -q" in text
    assert "(source no longer exists)" in text


def test_print_and_saved_output_match(project: Path, runner: CliRunner) -> None:
    make_stale(project, runner)
    out = project / "ctx.md"
    result = runner.invoke(__import__("documentledger.cli").cli.app, ["docs", "build-context", "--all", "--out", str(out), "--print"])
    assert result.exit_code == 0
    assert result.output == out.read_text(encoding="utf-8") + "\n"


def test_context_front_matter_uses_state_version_without_legacy_timestamp(project: Path, runner: CliRunner) -> None:
    make_stale(project, runner)
    result = runner.invoke(__import__("documentledger.cli").cli.app, ["docs", "build-context", "--all", "--print"])
    assert result.exit_code == 0
    lines = result.output.splitlines()
    assert "documentledger_schema: documentledger.context.v5" in lines[:6]
    assert any(line.startswith("scan_version: ") for line in lines[:5])
    assert any(line.startswith("state_version: ") for line in lines[:5])
    assert f"{'generated'}_at:" not in result.output


def test_affected_context_includes_only_target_section_and_source_unit(project: Path, runner: CliRunner) -> None:
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
    result = runner.invoke(__import__("documentledger.cli").cli.app, ["docs", "build-context", "--affected", "--print"])
    assert result.exit_code == 0
    assert "docs/usage.md :: Usage / Validate ledger state" in result.output
    assert "py:function:documentledger/cli.py::doctor" in result.output
    assert "py:function:documentledger/cli.py::scan" not in result.output
    assert 'def doctor(ctx: typer.Context, json: bool = typer.Option(False, "--json"))' in result.output


def test_doc_and_all_context_resolve_live_source_spans_and_excerpts(project: Path, runner: CliRunner) -> None:
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
            "Documents doctor.",
        ],
    )
    invoke_json(runner, ["scan"])
    for selector in (["--doc", "docs/usage.md"], ["--all"]):
        result = runner.invoke(__import__("documentledger.cli").cli.app, ["document", "build-context", *selector, "--print"])
        assert result.exit_code == 0
        assert "status: live" in result.output
        assert "signature: `doctor(ctx: typer.Context) -> None`" in result.output
        assert "def doctor(ctx: typer.Context) -> None:" in result.output


def test_bootstrap_context_contains_source_outlines_signatures_and_counts(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    write_precision_sample(project)
    invoke_json(runner, ["scan"])
    result = runner.invoke(__import__("documentledger.cli").cli.app, ["document", "build-context", "--bootstrap", "--print"])
    assert result.exit_code == 0
    assert "documentledger.context.v5" in result.output
    assert "## Repository documentation outline" in result.output
    assert "## Production source outline" in result.output
    assert "py:function:documentledger/cli.py::doctor" in result.output
    assert "signature: `doctor(ctx: typer.Context) -> None`" in result.output
    assert "## High-value source evidence" in result.output
    assert "## Bootstrap counts" in result.output
