from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from documentledger.cli import app
from tests.conftest import invoke_json, load_yaml


def test_add_link_creates_doc_record(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    data = invoke_json(runner, ["links", "add", "--doc", "README.md", "--source", "documentledger/cli.py"])
    assert data["result"]["linked_sources"] == ["documentledger/cli.py"]


def test_add_link_idempotent(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    invoke_json(runner, ["links", "add", "--doc", "README.md", "--source", "documentledger/cli.py"])
    data = invoke_json(runner, ["links", "add", "--doc", "README.md", "--source", "documentledger/cli.py"])
    record = load_yaml(next((project / ".documentledger" / "docs").glob("*.yaml")))
    storage = load_yaml(project / ".documentledger" / "storage.yaml")
    assert data["result"]["linked_sources"] == ["documentledger/cli.py"]
    assert record["version"] == 2
    assert storage["state_version"] == 2


def test_remove_link(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    invoke_json(runner, ["links", "add", "--doc", "README.md", "--source", "documentledger/cli.py"])
    data = invoke_json(runner, ["links", "remove", "--doc", "README.md", "--source", "documentledger/cli.py"])
    record = load_yaml(next((project / ".documentledger" / "docs").glob("*.yaml")))
    storage = load_yaml(project / ".documentledger" / "storage.yaml")
    assert data["result"]["linked_sources"] == []
    assert record["version"] == 3
    assert storage["state_version"] == 3


def test_remove_absent_link_is_noop(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    invoke_json(runner, ["links", "add", "--doc", "README.md", "--source", "documentledger/cli.py"])
    invoke_json(runner, ["links", "remove", "--doc", "README.md", "--source", "documentledger/missing.py"])
    record = load_yaml(next((project / ".documentledger" / "docs").glob("*.yaml")))
    storage = load_yaml(project / ".documentledger" / "storage.yaml")
    assert record["version"] == 2
    assert storage["state_version"] == 2


def test_absolute_paths_rejected(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    result = runner.invoke(app, ["--json", "links", "add", "--doc", str(project / "README.md"), "--source", "documentledger/cli.py"])
    assert result.exit_code != 0
    assert "invalid_path" in result.output


def test_path_traversal_rejected(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    result = runner.invoke(app, ["--json", "links", "add", "--doc", "../README.md", "--source", "documentledger/cli.py"])
    assert result.exit_code != 0
    assert "invalid_path" in result.output


@pytest.mark.parametrize("doc_path", [".", "./README.md", "docs//usage.md", "docs/", r"docs\\usage.md"])
def test_add_link_rejects_invalid_path_shapes(project: Path, runner: CliRunner, doc_path: str) -> None:
    invoke_json(runner, ["init"])
    result = runner.invoke(app, ["--json", "links", "add", "--doc", doc_path, "--source", "documentledger/cli.py"])
    assert result.exit_code != 0
    assert "invalid_path" in result.output


def test_missing_doc_rejected(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    result = runner.invoke(app, ["--json", "links", "add", "--doc", "missing.md", "--source", "documentledger/cli.py"])
    assert "missing_doc" in result.output


def test_missing_source_rejected(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    result = runner.invoke(app, ["--json", "links", "add", "--doc", "README.md", "--source", "missing.py"])
    assert "missing_source" in result.output
