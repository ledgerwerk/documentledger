from __future__ import annotations

from pathlib import Path

from tests.conftest import invoke_json, load_yaml, write_precision_sample


def write_map(path: Path, *, section: str, source_unit: str, reason: str) -> None:
    path.write_text(
        "schema: documentledger.mapping_proposal.v1\n"
        "doc_path: docs/usage.md\n"
        "sections:\n"
        f"  - section: {section}\n"
        "    links:\n"
        f"      - source_unit: {source_unit}\n"
        "        coverage: cli-command\n"
        "        impact: behavior\n"
        f"        reason: {reason}\n",
        encoding="utf-8",
    )


def test_import_map_directory_applies_batch_once(project: Path, runner) -> None:
    invoke_json(runner, ["init"])
    write_precision_sample(project)
    maps = project / "maps"
    maps.mkdir()
    write_map(maps / "scan.yaml", section="usage-run-scan", source_unit="py:function:documentledger/cli.py::scan", reason="Documents scan.")
    write_map(
        maps / "doctor.yaml",
        section="usage-validate-ledger-state",
        source_unit="py:function:documentledger/cli.py::doctor",
        reason="Documents doctor.",
    )
    validate = invoke_json(runner, ["links", "import-map", "--directory", str(maps), "--validate"])["result"]
    apply = invoke_json(runner, ["links", "import-map", "--directory", str(maps), "--check-and-apply"])["result"]
    record = load_yaml(next((project / ".ledger" / "documentledger" / "data" / "docs").glob("*.yaml")))
    assert validate["planned_edges"] == 2
    assert apply["planned_edges"] == 2
    assert apply["added_edges"] == 2
    assert apply["changed_documents"] == 1
    assert sorted(record["linked_sources"]) == ["documentledger/cli.py"]


def test_import_map_reapply_is_noop(project: Path, runner) -> None:
    invoke_json(runner, ["init"])
    write_precision_sample(project)
    mapping = project / "mapping.yaml"
    write_map(mapping, section="usage-run-scan", source_unit="py:function:documentledger/cli.py::scan", reason="Documents scan.")
    first = invoke_json(runner, ["links", "import-map", "--file", str(mapping), "--check-and-apply"])["result"]
    second = invoke_json(runner, ["links", "import-map", "--file", str(mapping), "--check-and-apply"])["result"]
    assert first["added_edges"] == 1
    assert second["added_edges"] == 0
    assert second["unchanged_edges"] == 1


def test_import_map_accepts_empty_reviewed_document_as_noop(project: Path, runner) -> None:
    invoke_json(runner, ["init"])
    write_precision_sample(project)
    empty = project / "empty.yaml"
    empty.write_text(
        "schema: documentledger.mapping_proposal.v1\ndoc_path: docs/usage.md\nsections: []\n",
        encoding="utf-8",
    )
    result = invoke_json(runner, ["link", "import-map", "--file", str(empty), "--check-and-apply"])
    assert result["result"]["empty_mapping_files"] == 1
    assert result["result"]["documents"] == 0
    assert result["result"]["planned_edges"] == 0
    assert not (project / ".ledger" / "documentledger" / "data" / "docs").exists()
    assert any(event["event"] == "mapping_skipped_empty" for event in result["events"])


def test_import_map_mixed_empty_and_reviewed_files_preserves_empty_noop(project: Path, runner) -> None:
    invoke_json(runner, ["init"])
    write_precision_sample(project)
    maps = project / "maps"
    maps.mkdir()
    write_map(maps / "scan.yaml", section="usage-run-scan", source_unit="py:function:documentledger/cli.py::scan", reason="Documents scan.")
    (maps / "index.yaml").write_text(
        "schema: documentledger.mapping_proposal.v1\ndoc_path: README.md\nsections: []\n",
        encoding="utf-8",
    )
    result = invoke_json(runner, ["link", "import-map", "--directory", str(maps), "--check-and-apply"])["result"]
    assert result["empty_mapping_files"] == 1
    assert result["documents"] == 1
    assert result["added_edges"] == 1


def test_replace_section_preserves_all_supplied_edges(project: Path, runner) -> None:
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
            "usage-run-scan",
            "--source-unit",
            "py:function:documentledger/cli.py::scan",
            "--coverage",
            "cli-command",
            "--impact",
            "behavior",
            "--reason",
            "Old link.",
        ],
    )
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
        "        reason: Documents scan.\n"
        "      - source_unit: py:function:documentledger/cli.py::doctor\n"
        "        coverage: cli-command\n"
        "        impact: behavior\n"
        "        reason: Documents doctor.\n",
        encoding="utf-8",
    )
    invoke_json(runner, ["links", "import-map", "--file", str(mapping), "--check-and-apply", "--replace-section"])
    record = load_yaml(next((project / ".ledger" / "documentledger" / "data" / "docs").glob("*.yaml")))
    section = next(section for section in record["sections"] if section["heading_slug"] == "usage-run-scan")
    assert [link["source_id"] for link in section["links"]] == [
        "py:function:documentledger/cli.py::doctor",
        "py:function:documentledger/cli.py::scan",
    ]
