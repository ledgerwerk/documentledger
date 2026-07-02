from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from tests.conftest import assert_no_timestamp_keys, invoke_json, load_yaml


def init_and_link(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    invoke_json(runner, ["links", "add", "--doc", "README.md", "--source", "documentledger/cli.py"])


def test_first_scan_records_baseline(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    data = invoke_json(runner, ["scan"])["result"]
    storage = load_yaml(project / ".documentledger" / "storage.yaml")
    scan_record = load_yaml(project / ".documentledger" / "scans" / "scan-0001.yaml")
    assert data["scan_id"] == "scan-0001"
    assert data["unchanged"] is False
    assert data["changed_sources"] == []
    assert data["stale_docs"] == []
    assert storage["state_version"] == 2
    assert scan_record["schema"] == "documentledger.scan.v2"
    assert scan_record["version"] == 2
    assert_no_timestamp_keys(scan_record)


def test_unchanged_scan_reuses_latest_scan_id(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    first = invoke_json(runner, ["scan"])["result"]
    second = invoke_json(runner, ["scan"])["result"]
    storage = load_yaml(project / ".documentledger" / "storage.yaml")
    scan_files = sorted((project / ".documentledger" / "scans").glob("scan-*.yaml"))
    assert first["scan_id"] == "scan-0001"
    assert second["scan_id"] == "scan-0001"
    assert second["unchanged"] is True
    assert second["changed_sources"] == []
    assert second["deleted_sources"] == []
    assert second["stale_docs"] == []
    assert second["unlinked_changed_sources"] == []
    assert storage["state_version"] == 2
    assert [path.name for path in scan_files] == ["scan-0001.yaml"]


def test_second_scan_detects_changed_source(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    invoke_json(runner, ["scan"])
    (project / "documentledger" / "cli.py").write_text("print('changed')\n", encoding="utf-8")
    data = invoke_json(runner, ["scan"])["result"]
    storage = load_yaml(project / ".documentledger" / "storage.yaml")
    assert data["changed_sources"] == ["documentledger/cli.py"]
    assert data["scan_id"] == "scan-0002"
    assert data["unchanged"] is False
    assert storage["state_version"] == 3


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


def test_doc_only_change_creates_new_scan_without_marking_docs_stale(project: Path, runner: CliRunner) -> None:
    init_and_link(project, runner)
    invoke_json(runner, ["scan"])
    (project / "README.md").write_text("# docs changed\n", encoding="utf-8")
    data = invoke_json(runner, ["scan"])["result"]
    assert data["scan_id"] == "scan-0002"
    assert data["changed_sources"] == []
    assert data["deleted_sources"] == []
    assert data["stale_docs"] == []
