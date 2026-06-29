from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from tests.conftest import invoke_json


def test_status_reports_initialized_workspace(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init", "--project-name", "demo"])
    data = invoke_json(runner, ["status"])
    result = data["result"]
    assert result["initialized"] is True
    assert result["config_path"] == "documentledger.toml"
    assert result["storage_dir"] == ".documentledger"


def test_status_reports_missing_workspace(tmp_path: Path, monkeypatch, runner: CliRunner) -> None:
    monkeypatch.chdir(tmp_path)
    data = invoke_json(runner, ["status"])
    assert data["ok"] is True
    assert data["result"]["initialized"] is False
    assert data["result"]["remediation"]


def test_json_status_envelope_stable(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    data = invoke_json(runner, ["status"])
    assert set(data) == {"ok", "command", "result", "events"}
    assert data["command"] == "status"
