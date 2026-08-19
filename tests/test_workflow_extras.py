from __future__ import annotations

from pathlib import Path

from tests.conftest import invoke_json, load_yaml, write_precision_sample


def test_coverage_reports_inventory(project: Path, runner) -> None:
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
            "Documents the scan command.",
        ],
    )
    invoke_json(runner, ["scan"])
    result = invoke_json(runner, ["coverage"])["result"]
    assert result["documents"]["total"] >= 2
    assert result["sections"]["linked"] >= 1
    assert result["sources"]["units"] >= 1


def test_links_propose_writes_mapping_files(project: Path, runner) -> None:
    invoke_json(runner, ["init"])
    (project / "docs").mkdir(exist_ok=True)
    (project / "documentledger" / "cli.py").write_text("def doctor():\n    pass\n", encoding="utf-8")
    (project / "docs" / "usage.md").write_text("## Doctor\n\nSee `documentledger/cli.py` and `doctor`.\n", encoding="utf-8")
    invoke_json(runner, ["scan"])
    out_dir = project / "proposals"
    result = invoke_json(runner, ["links", "propose", "--all-docs", "--out-dir", str(out_dir)])["result"]
    assert result["proposal_files"]
    payload = load_yaml(Path(result["proposal_files"][0]))
    assert payload["schema"] == "documentledger.mapping_proposal.v1"


def test_link_propose_accepts_out_alias_with_same_behavior(project: Path, runner) -> None:
    invoke_json(runner, ["init"])
    (project / "docs").mkdir(exist_ok=True)
    (project / "documentledger" / "cli.py").write_text("def doctor():\n    pass\n", encoding="utf-8")
    (project / "docs" / "usage.md").write_text("## Doctor\n\nSee `documentledger/cli.py` and `doctor`.\n", encoding="utf-8")
    invoke_json(runner, ["scan"])
    out_dir = project / "proposals-out"
    out_dir_alias = project / "proposals-alias"
    canonical = invoke_json(runner, ["link", "propose", "--all-docs", "--out-dir", str(out_dir)])
    alias = invoke_json(runner, ["link", "propose", "--all-docs", "--out", str(out_dir_alias)])
    assert canonical["result"]["documents"] == alias["result"]["documents"]
    assert canonical["result"]["proposed_sections"] == alias["result"]["proposed_sections"]
    assert canonical["result"]["proposed_edges"] == alias["result"]["proposed_edges"]


def test_link_proposals_use_code_evidence_and_exclude_test_helpers(project: Path, runner) -> None:
    invoke_json(runner, ["init"])
    (project / "tests").mkdir()
    (project / "tests" / "test_helpers.py").write_text("def build():\n    pass\n", encoding="utf-8")
    (project / "documentledger" / "dictionary.py").write_text(
        "class Dictionary:\n    def supports(self, key: str) -> bool:\n        return bool(key)\n",
        encoding="utf-8",
    )
    (project / "README.md").write_text(
        "# API\n\n"
        "See https://github.com/example/project/blob/main/README.md.\n\n"
        "Build the package before use.\n\n"
        "Use `Dictionary` and `Dictionary.supports`.\n",
        encoding="utf-8",
    )
    invoke_json(runner, ["scan"])
    out_dir = project / "proposals"
    result = invoke_json(runner, ["link", "propose", "--all-docs", "--out-dir", str(out_dir)])
    payloads = [load_yaml(path) for path in out_dir.glob("*.yaml")]
    links = [link for payload in payloads for section in payload.get("sections", []) for link in section.get("links", [])]
    source_units = {str(link["source_unit"]) for link in links}
    assert any("Dictionary" in source_id for source_id in source_units)
    assert not any("tests/test_helpers.py" in source_id for source_id in source_units)
    assert result["result"]["rejected_candidates"]["excluded_test_units"] > 0
