from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from documentledger.cli import app
from tests.conftest import invoke_json


def test_success_envelopes_parse(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    for args in (["status"], ["doctor"], ["scan"], ["docs", "stale"]):
        data = invoke_json(runner, list(args))
        assert data["ok"] is True
        assert "result" in data


def test_error_envelope_parse(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    result = runner.invoke(app, ["--json", "links", "add", "--doc", "/x", "--source", "documentledger/cli.py"])
    assert result.exit_code != 0
    data = json.loads(result.output)
    assert data["ok"] is False
    assert data["error"]["code"] == "invalid_path"


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
