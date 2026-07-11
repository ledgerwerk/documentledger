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
