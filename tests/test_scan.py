from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from tests.conftest import invoke_json


def init_and_link(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    invoke_json(runner, ["links", "add", "--doc", "README.md", "--source", "documentledger/cli.py"])


def test_first_scan_records_baseline(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    data = invoke_json(runner, ["scan"])["result"]
    assert data["changed_sources"] == []
    assert data["stale_docs"] == []


def test_second_scan_detects_changed_source(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    invoke_json(runner, ["scan"])
    (project / "documentledger" / "cli.py").write_text("print('changed')\n", encoding="utf-8")
    data = invoke_json(runner, ["scan"])["result"]
    assert data["changed_sources"] == ["documentledger/cli.py"]


def test_changed_linked_source_marks_doc_stale(project: Path, runner: CliRunner) -> None:
    init_and_link(project, runner)
    invoke_json(runner, ["scan"])
    (project / "documentledger" / "cli.py").write_text("print('changed')\n", encoding="utf-8")
    data = invoke_json(runner, ["scan"])["result"]
    assert data["stale_docs"] == ["README.md"]


def test_changed_unlinked_source_reported(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    invoke_json(runner, ["scan"])
    (project / "documentledger" / "extra.py").write_text("x = 1\n", encoding="utf-8")
    data = invoke_json(runner, ["scan"])["result"]
    assert data["unlinked_changed_sources"] == ["documentledger/extra.py"]


def test_deleted_linked_source_marks_doc_stale(project: Path, runner: CliRunner) -> None:
    init_and_link(project, runner)
    invoke_json(runner, ["scan"])
    (project / "documentledger" / "cli.py").unlink()
    data = invoke_json(runner, ["scan"])["result"]
    assert data["deleted_sources"] == ["documentledger/cli.py"]
    assert data["stale_docs"] == ["README.md"]
