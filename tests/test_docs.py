from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from documentledger.cli import app
from tests.conftest import invoke_json


def test_docs_list_shows_known_docs(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    invoke_json(runner, ["scan"])
    data = invoke_json(runner, ["docs", "list"])
    assert data["result"]["docs"] == ["README.md"]


def test_docs_stale_shows_latest_scan_stale(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    invoke_json(runner, ["links", "add", "--doc", "README.md", "--source", "documentledger/cli.py"])
    invoke_json(runner, ["scan"])
    (project / "documentledger" / "cli.py").write_text("changed\n", encoding="utf-8")
    invoke_json(runner, ["scan"])
    data = invoke_json(runner, ["docs", "stale"])
    assert data["result"]["stale_docs"][0]["doc_path"] == "README.md"


def test_mark_fresh_updates_fields(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    invoke_json(runner, ["links", "add", "--doc", "README.md", "--source", "documentledger/cli.py"])
    invoke_json(runner, ["scan"])
    (project / "documentledger" / "cli.py").write_text("changed\n", encoding="utf-8")
    scan = invoke_json(runner, ["scan"])["result"]["scan_id"]
    data = invoke_json(runner, ["mark-fresh", "--doc", "README.md", "--reason", f"Docs updated after scan {scan}."])
    assert data["result"]["updated_docs"] == ["README.md"]


def test_mark_fresh_requires_reason(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    result = runner.invoke(app, ["--json", "mark-fresh", "--doc", "README.md"])
    assert result.exit_code != 0
