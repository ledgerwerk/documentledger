from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from tests.conftest import invoke_json, invoke_json_may_fail, write_precision_sample


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


def test_check_failure_is_one_error_envelope(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    write_precision_sample(project)
    invoke_json(runner, ["scan"])
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
    (project / "docs" / "usage.md").write_text("# Usage\n\n## Run a scan\n\nRun scan.\n", encoding="utf-8")
    invoke_json(runner, ["scan"])

    exit_code, data = invoke_json_may_fail(runner, ["check"])

    assert exit_code == 1
    assert data["ok"] is False
    assert data["error"]["code"] == "check-failed"
    assert data["error"]["details"]["issues"]
