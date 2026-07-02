from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from tests.conftest import assert_no_timestamp_keys, invoke_json, load_yaml, write_precision_sample


def init_and_link(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    invoke_json(runner, ["links", "add", "--doc", "README.md", "--source", "documentledger/cli.py"])


def test_first_scan_records_baseline(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    data = invoke_json(runner, ["scan"])["result"]
    storage = load_yaml(project / ".documentledger" / "storage.yaml")
    scan_record = load_yaml(project / ".documentledger" / "scan.yaml")
    assert data["version"] == 1
    assert data["unchanged"] is False
    assert data["changed_sources"] == []
    assert data["stale_docs"] == []
    assert storage["state_version"] == 2
    assert scan_record["schema"] == "documentledger.scan.v4"
    assert scan_record["version"] == 1
    assert "source_units" in scan_record
    assert not (project / ".documentledger" / "scans").exists()
    assert_no_timestamp_keys(scan_record)


def test_unchanged_scan_reuses_latest_scan_version(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    first = invoke_json(runner, ["scan"])["result"]
    second = invoke_json(runner, ["scan"])["result"]
    storage = load_yaml(project / ".documentledger" / "storage.yaml")
    assert first["version"] == 1
    assert second["version"] == 1
    assert second["unchanged"] is True
    assert second["changed_sources"] == []
    assert second["deleted_sources"] == []
    assert second["stale_docs"] == []
    assert second["unlinked_changed_sources"] == []
    assert storage["state_version"] == 2
    assert (project / ".documentledger" / "scan.yaml").exists()
    assert not (project / ".documentledger" / "scans").exists()


def test_second_scan_detects_changed_source(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    invoke_json(runner, ["scan"])
    (project / "documentledger" / "cli.py").write_text("print('changed')\n", encoding="utf-8")
    data = invoke_json(runner, ["scan"])["result"]
    storage = load_yaml(project / ".documentledger" / "storage.yaml")
    assert data["changed_sources"] == ["documentledger/cli.py"]
    assert data["version"] == 2
    assert data["unchanged"] is False
    assert storage["state_version"] == 3
    assert load_yaml(project / ".documentledger" / "scan.yaml")["version"] == 2


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


def test_doc_only_change_rewrites_scan_yaml_without_marking_docs_stale(project: Path, runner: CliRunner) -> None:
    init_and_link(project, runner)
    invoke_json(runner, ["scan"])
    (project / "README.md").write_text("# docs changed\n", encoding="utf-8")
    data = invoke_json(runner, ["scan"])["result"]
    assert data["version"] == 2
    assert data["changed_sources"] == []
    assert data["deleted_sources"] == []
    assert data["stale_docs"] == []


def test_section_linked_doctor_change_only_affects_doctor_section(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    write_precision_sample(project)
    invoke_json(
        runner,
        [
            "links",
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
            "Documents the doctor command.",
        ],
    )
    invoke_json(runner, ["scan"])
    cli_path = project / "documentledger" / "cli.py"
    cli_path.write_text(
        cli_path.read_text(encoding="utf-8").replace(
            "def doctor(ctx: typer.Context) -> None:",
            'def doctor(ctx: typer.Context, json: bool = typer.Option(False, "--json")) -> None:',
        ),
        encoding="utf-8",
    )
    data = invoke_json(runner, ["scan"])["result"]
    assert data["changed_sources"] == ["documentledger/cli.py"]
    assert [item["source_id"] for item in data["changed_units"]] == ["py:function:documentledger/cli.py::doctor"]
    assert [item["section_id"] for item in data["affected_sections"]] == ["md:section:docs/usage.md::usage-validate-ledger-state"]
    assert data["stale_docs"] == ["docs/usage.md"]


def test_comment_only_change_does_not_affect_section_linked_docs(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    write_precision_sample(project)
    invoke_json(
        runner,
        [
            "links",
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
            "Documents the doctor command.",
        ],
    )
    invoke_json(runner, ["scan"])
    cli_path = project / "documentledger" / "cli.py"
    cli_path.write_text(cli_path.read_text(encoding="utf-8").replace("def doctor", "# comment\n\ndef doctor"), encoding="utf-8")
    data = invoke_json(runner, ["scan"])["result"]
    assert data["affected_sections"] == []
    assert data["stale_docs"] == []
