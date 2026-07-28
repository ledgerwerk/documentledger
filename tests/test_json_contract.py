from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from tests.conftest import invoke_json, invoke_json_may_fail


def test_success_envelopes_parse(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    for args in (["status"], ["doctor"], ["scan"], ["document", "stale"]):
        data = invoke_json(runner, list(args))
        assert data["ok"] is True
        assert "result" in data
        # Verify ledgerwerk.cli.v1 envelope
        assert data["schema"] == "ledgerwerk.cli.v1"
        assert data["tool"] == "documentledger"
        assert "command" in data
        assert "events" in data
        assert "warnings" in data


def test_error_envelope_parse(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    exit_code, data = invoke_json_may_fail(runner, ["link", "add", "--doc", "/x", "--source", "documentledger/cli.py"])
    assert exit_code != 0
    assert data["ok"] is False
    assert data["schema"] == "ledgerwerk.cli.v1"
    assert data["tool"] == "documentledger"
    assert data["error"]["code"] == "invalid-path"


def test_global_json_before_command(project: Path, runner: CliRunner) -> None:
    data = invoke_json(runner, ["status"])
    assert data["command"] == "status"


def test_scan_and_status_json_contracts_use_versions(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    scan = invoke_json(runner, ["scan"])
    status = invoke_json(runner, ["status"])
    assert scan["result"]["version"] == 1
    assert "scan_id" not in scan["result"]
    assert status["result"]["last_scan_version"] == 1
    assert "last_scan_id" not in status["result"]
