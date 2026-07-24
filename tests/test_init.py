from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from documentledger.cli import app
from tests.conftest import assert_no_timestamp_keys, invoke_json, load_yaml


def test_init_creates_config_and_storage(project: Path, runner: CliRunner) -> None:
    data = invoke_json(runner, ["init", "--project-name", "demo"])
    assert data["ok"] is True
    assert (project / ".ledger" / "ledger.toml").exists()
    assert (project / ".ledger" / "documentledger" / "config.toml").exists()
    assert (project / ".ledger" / "documentledger" / "data" / "storage.yaml").exists()
    assert (project / ".ledger" / "documentledger" / "data" / "docs").is_dir() is False
    assert not (project / ".documentledger").exists()
    storage = load_yaml(project / ".ledger" / "documentledger" / "data" / "storage.yaml")
    assert storage["schema_version"] == 5
    assert storage["state_version"] == 1
    assert "next_scan_number" not in storage
    assert "last_scan_id" not in storage
    assert_no_timestamp_keys(storage)


def test_legacy_init_options_are_rejected(project: Path, runner: CliRunner) -> None:
    result = runner.invoke(app, ["--json", "init", "--hidden-config"])
    assert result.exit_code != 0
    assert "legacy_init_options_unsupported" in result.output


def test_reinitialization_fails_cleanly(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    result = runner.invoke(app, ["--json", "init"])
    assert result.exit_code != 0
    assert "already_initialized" in result.output


def test_external_storage_option_is_rejected(project: Path, runner: CliRunner) -> None:
    result = runner.invoke(app, ["--json", "init", "--documentledger-dir", "../ledger-state"])
    assert result.exit_code != 0
    assert "legacy_init_options_unsupported" in result.output
