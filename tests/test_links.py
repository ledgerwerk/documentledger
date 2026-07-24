from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from documentledger.cli import app
from tests.conftest import invoke_json, load_yaml, write_precision_sample


def test_add_link_creates_doc_record(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    data = invoke_json(runner, ["links", "add", "--doc", "README.md", "--source", "documentledger/cli.py"])
    assert data["result"]["linked_sources"] == ["documentledger/cli.py"]


def test_add_link_idempotent(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    invoke_json(runner, ["links", "add", "--doc", "README.md", "--source", "documentledger/cli.py"])
    data = invoke_json(runner, ["links", "add", "--doc", "README.md", "--source", "documentledger/cli.py"])
    record = load_yaml(next((project / ".ledger" / "documentledger" / "data" / "docs").glob("*.yaml")))
    storage = load_yaml(project / ".ledger" / "documentledger" / "data" / "storage.yaml")
    assert data["result"]["linked_sources"] == ["documentledger/cli.py"]
    assert record["schema"] == "documentledger.doc_record.v4"
    assert record["last_fresh_scan_version"] == 0
    assert "last_fresh_scan_id" not in record
    assert record["version"] == 2
    assert storage["state_version"] == 2


def test_remove_link(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    invoke_json(runner, ["links", "add", "--doc", "README.md", "--source", "documentledger/cli.py"])
    data = invoke_json(runner, ["links", "remove", "--doc", "README.md", "--source", "documentledger/cli.py"])
    record = load_yaml(next((project / ".ledger" / "documentledger" / "data" / "docs").glob("*.yaml")))
    storage = load_yaml(project / ".ledger" / "documentledger" / "data" / "storage.yaml")
    assert data["result"]["linked_sources"] == []
    assert record["version"] == 3
    assert storage["state_version"] == 3


def test_remove_absent_link_is_noop(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    invoke_json(runner, ["links", "add", "--doc", "README.md", "--source", "documentledger/cli.py"])
    invoke_json(runner, ["links", "remove", "--doc", "README.md", "--source", "documentledger/missing.py"])
    record = load_yaml(next((project / ".ledger" / "documentledger" / "data" / "docs").glob("*.yaml")))
    storage = load_yaml(project / ".ledger" / "documentledger" / "data" / "storage.yaml")
    assert record["version"] == 2
    assert storage["state_version"] == 2


def test_absolute_paths_rejected(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    result = runner.invoke(app, ["--json", "links", "add", "--doc", str(project / "README.md"), "--source", "documentledger/cli.py"])
    assert result.exit_code != 0
    assert "invalid_path" in result.output


def test_path_traversal_rejected(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    result = runner.invoke(app, ["--json", "links", "add", "--doc", "../README.md", "--source", "documentledger/cli.py"])
    assert result.exit_code != 0
    assert "invalid_path" in result.output


@pytest.mark.parametrize("doc_path", [".", "./README.md", "docs//usage.md", "docs/", r"docs\\usage.md"])
def test_add_link_rejects_invalid_path_shapes(project: Path, runner: CliRunner, doc_path: str) -> None:
    invoke_json(runner, ["init"])
    result = runner.invoke(app, ["--json", "links", "add", "--doc", doc_path, "--source", "documentledger/cli.py"])
    assert result.exit_code != 0
    assert "invalid_path" in result.output


def test_missing_doc_rejected(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    result = runner.invoke(app, ["--json", "links", "add", "--doc", "missing.md", "--source", "documentledger/cli.py"])
    assert "missing_doc" in result.output


def test_missing_source_rejected(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    result = runner.invoke(app, ["--json", "links", "add", "--doc", "README.md", "--source", "missing.py"])
    assert "missing_source" in result.output


def test_add_section_link_creates_precise_section_edge(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    write_precision_sample(project)
    data = invoke_json(
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
    record = data["result"]
    assert record["linked_sources"] == ["documentledger/cli.py"]
    section = next(section for section in record["sections"] if section["heading_slug"] == "usage-validate-ledger-state")
    assert section["links"][0]["source_id"] == "py:function:documentledger/cli.py::doctor"
    assert set(section["links"][0]["tracked_hashes"]) == {"signature_hash", "decorator_hash", "public_contract_hash"}


def test_import_map_validate_and_apply(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    write_precision_sample(project)
    mapping = project / "mapping.yaml"
    mapping.write_text(
        "schema: documentledger.mapping_proposal.v1\n"
        "doc_path: docs/usage.md\n"
        "sections:\n"
        "  - section: usage-run-scan\n"
        "    links:\n"
        "      - source_unit: py:function:documentledger/cli.py::scan\n"
        "        coverage: cli-command\n"
        "        impact: behavior\n"
        "        reason: Documents the scan command.\n",
        encoding="utf-8",
    )
    validate = invoke_json(runner, ["links", "import-map", "--file", str(mapping), "--validate"])["result"]
    apply = invoke_json(runner, ["links", "import-map", "--file", str(mapping), "--apply"])["result"]
    record = load_yaml(next((project / ".ledger" / "documentledger" / "data" / "docs").glob("*.yaml")))
    assert validate["applied"] is False
    assert apply["applied"] is True
    assert record["linked_sources"] == ["documentledger/cli.py"]
