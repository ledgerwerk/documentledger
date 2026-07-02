from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from documentledger.cli import app
from tests.conftest import assert_no_timestamp_keys, dump_yaml, invoke_json, load_yaml


def timestamp_key(prefix: str) -> str:
    return f"{prefix}_at"


def test_status_config_only_when_storage_missing(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    (project / ".documentledger" / "storage.yaml").unlink()
    data = invoke_json(runner, ["status"])
    result = data["result"]
    assert result["state"] == "config_only"
    assert result["initialized"] is False
    assert result["storage_present"] is False
    assert result["config_path"] == "documentledger.toml"


def test_status_states_distinguish_initialized(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    data = invoke_json(runner, ["status"])
    result = data["result"]
    assert result["state"] == "initialized"
    assert result["initialized"] is True
    assert result["storage_present"] is True


def test_mark_fresh_rejects_unlinked_doc(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    invoke_json(runner, ["scan"])
    result = runner.invoke(app, ["--json", "mark-fresh", "--doc", "README.md", "--reason", "r"])
    assert result.exit_code != 0
    data = json.loads(result.output)
    assert data["ok"] is False
    assert data["error"]["code"] == "unlinked_doc"


def test_mark_fresh_allow_unlinked_opt_in(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    invoke_json(runner, ["scan"])
    data = invoke_json(runner, ["mark-fresh", "--doc", "README.md", "--allow-unlinked", "--reason", "nav page"])
    assert data["result"]["updated_docs"] == ["README.md"]


def test_build_context_useful_with_unlinked_changed_no_stale(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    invoke_json(runner, ["scan"])
    (project / "documentledger" / "new.py").write_text("x = 1\n", encoding="utf-8")
    invoke_json(runner, ["scan"])
    result = runner.invoke(app, ["docs", "build-context", "--all", "--print"])
    assert result.exit_code == 0
    assert "No stale docs." in result.output
    assert "documentledger/new.py" in result.output


def test_build_context_include_unlinked_bootstrap(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    invoke_json(runner, ["scan"])
    result = runner.invoke(app, ["docs", "build-context", "--all", "--include-unlinked", "--print"])
    assert result.exit_code == 0
    assert "Unlinked sources (bootstrap)" in result.output
    assert "documentledger/cli.py" in result.output


def test_error_envelope_preserves_command_name(tmp_path: Path, monkeypatch, runner: CliRunner) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["--json", "scan"])
    assert result.exit_code != 0
    data = json.loads(result.output)
    assert data["command"] == "scan"
    assert data["ok"] is False
    assert data["error"]["code"] == "workspace_not_found"


def test_human_error_output_is_not_json(tmp_path: Path, monkeypatch, runner: CliRunner) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["scan"])
    assert result.exit_code != 0
    assert not result.output.lstrip().startswith("{")
    assert "Error:" in result.output


def test_human_error_includes_remediation_hint(tmp_path: Path, monkeypatch, runner: CliRunner) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["scan"])
    assert "Run `docledger init`" in result.output


def test_timestamp_keys_absent_from_persisted_state_and_rendered_context(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    invoke_json(runner, ["links", "add", "--doc", "README.md", "--source", "documentledger/cli.py"])
    invoke_json(runner, ["scan"])
    (project / "documentledger" / "cli.py").write_text("changed\n", encoding="utf-8")
    invoke_json(runner, ["scan"])
    invoke_json(runner, ["mark-fresh", "--doc", "README.md", "--reason", "Docs updated after scan scan-0002."])
    storage_dir = project / ".documentledger"
    assert_no_timestamp_keys(load_yaml(storage_dir / "storage.yaml"))
    assert_no_timestamp_keys(load_yaml(storage_dir / "scans" / "scan-0002.yaml"))
    assert_no_timestamp_keys(load_yaml(next((storage_dir / "docs").glob("*.yaml"))))
    result = runner.invoke(app, ["docs", "build-context", "--all", "--print"])
    assert f"{timestamp_key('generated')}:" not in result.output


def test_workspace_load_migrates_v1_state(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    invoke_json(runner, ["links", "add", "--doc", "README.md", "--source", "documentledger/cli.py"])
    invoke_json(runner, ["scan"])
    storage_path = project / ".documentledger" / "storage.yaml"
    scan_path = project / ".documentledger" / "scans" / "scan-0001.yaml"
    doc_path = next((project / ".documentledger" / "docs").glob("*.yaml"))

    legacy_storage = load_yaml(storage_path)
    legacy_storage["schema_version"] = 1
    legacy_storage[timestamp_key("created")] = "2026-01-01T00:00:00Z"
    legacy_storage[timestamp_key("updated")] = "2026-01-01T00:00:00Z"
    legacy_storage.pop("state_version", None)
    dump_yaml(storage_path, legacy_storage)

    legacy_scan = load_yaml(scan_path)
    legacy_scan["schema"] = "documentledger.scan.v1"
    legacy_scan[timestamp_key("created")] = "2026-01-01T00:00:00Z"
    legacy_scan.pop("version", None)
    dump_yaml(scan_path, legacy_scan)

    legacy_doc = load_yaml(doc_path)
    legacy_doc["schema"] = "documentledger.doc_record.v1"
    legacy_doc[timestamp_key("updated")] = "2026-01-01T00:00:00Z"
    legacy_doc.pop("version", None)
    dump_yaml(doc_path, legacy_doc)

    status = invoke_json(runner, ["status"])["result"]
    migrated_storage = load_yaml(storage_path)
    migrated_scan = load_yaml(scan_path)
    migrated_doc = load_yaml(doc_path)
    assert status["initialized"] is True
    assert migrated_storage["schema_version"] == 2
    assert int(migrated_storage["state_version"]) >= 1
    assert migrated_scan["schema"] == "documentledger.scan.v2"
    assert "version" in migrated_scan
    assert migrated_doc["schema"] == "documentledger.doc_record.v2"
    assert "version" in migrated_doc
    assert_no_timestamp_keys(migrated_storage)
    assert_no_timestamp_keys(migrated_scan)
    assert_no_timestamp_keys(migrated_doc)
