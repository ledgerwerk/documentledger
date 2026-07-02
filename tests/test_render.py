from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from tests.conftest import invoke_json


def make_stale(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    config = project / "documentledger.toml"
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
    assert "documentledger_schema: documentledger.context.v1" in lines[:5]
    assert any(line.startswith("state_version: ") for line in lines[:5])
    assert f"{'generated'}_at:" not in result.output
