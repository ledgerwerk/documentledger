from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from documentledger.cli import app
from tests.conftest import assert_no_timestamp_keys, invoke_json, load_yaml


def test_init_creates_config_and_storage(project: Path, runner: CliRunner) -> None:
    data = invoke_json(runner, ["init", "--project-name", "demo"])
    assert data["ok"] is True
    assert (project / "documentledger.toml").exists()
    assert (project / ".documentledger" / "storage.yaml").exists()
    assert (project / ".documentledger" / "docs").is_dir()
    assert (project / ".documentledger" / "rendered").is_dir()
    assert not (project / ".documentledger" / "scans").exists()
    storage = load_yaml(project / ".documentledger" / "storage.yaml")
    assert storage["schema_version"] == 4
    assert storage["state_version"] == 1
    assert "next_scan_number" not in storage
    assert "last_scan_id" not in storage
    assert_no_timestamp_keys(storage)


def test_hidden_config(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init", "--hidden-config"])
    assert (project / ".documentledger.toml").exists()


def test_reinitialization_fails_cleanly(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    result = runner.invoke(app, ["--json", "init"])
    assert result.exit_code != 0
    assert "already_initialized" in result.output


def test_external_storage_paths_resolved_from_config_root(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init", "--documentledger-dir", "../ledger-state"])
    assert (project.parent / "ledger-state" / "storage.yaml").exists()
    status = invoke_json(runner, ["status"])["result"]
    assert status["storage_dir"] == "../ledger-state"
