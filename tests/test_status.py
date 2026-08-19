from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from tests.conftest import invoke_json


def test_status_reports_initialized_workspace(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init", "--project-name", "demo"])
    data = invoke_json(runner, ["status"])
    result = data["result"]
    assert result["initialized"] is True
    assert result["config_path"] == ".ledger/documentledger/config.toml"
    assert result["storage_dir"] == ".ledger/documentledger/data"
    assert result["last_scan_version"] is None


def test_status_reports_latest_scan_version_after_scan(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    invoke_json(runner, ["scan"])
    data = invoke_json(runner, ["status"])
    assert data["result"]["last_scan_version"] == 1


def test_status_recommendations_use_canonical_commands_and_separate_freshness(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    before_scan = invoke_json(runner, ["status"])["result"]
    assert before_scan["recommended_command"] == "documentledger scan"
    assert before_scan["freshness_state"] == "clean"
    assert before_scan["mapping_state"] == "review_required"
    invoke_json(runner, ["scan"])
    after_scan = invoke_json(runner, ["status"])["result"]
    assert ".ledger/documentledger/data" not in after_scan["recommended_command"]
    assert "docledger" not in after_scan["recommended_command"]


def test_status_reports_missing_workspace(tmp_path: Path, monkeypatch, runner: CliRunner) -> None:
    monkeypatch.chdir(tmp_path)
    data = invoke_json(runner, ["status"])
    assert data["ok"] is True
    assert data["result"]["initialized"] is False
    assert data["result"]["remediation"]


def test_json_status_envelope_stable(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    data = invoke_json(runner, ["status"])
    # ledgerwerk.cli.v1 envelope
    assert set(data) == {"schema", "ok", "tool", "command", "result", "events", "warnings"}
    assert data["schema"] == "ledgerwerk.cli.v1"
    assert data["tool"] == "documentledger"
    assert data["command"] == "status"
    assert data["ok"] is True
