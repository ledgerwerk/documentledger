from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from documentledger.storage import doc_record_path, load_doc_record, load_workspace
from tests.conftest import dump_yaml, invoke_json, invoke_json_may_fail, load_yaml, write_precision_sample


def write_generated_doc(project: Path, *, include_old: bool = True, prefix: str = "") -> None:
    (project / "docs").mkdir(exist_ok=True)
    old = "## Old release\n\nOld content.\n\n" if include_old else ""
    (project / "docs" / "generated.md").write_text(
        f"# Releases\n\n{prefix}{old}## Keep\n\nKeep content.\n",
        encoding="utf-8",
    )


def generated_record(project: Path):
    workspace = load_workspace(start=project)
    return workspace, load_doc_record(workspace, "docs/generated.md")


def test_removed_unlinked_section_is_pruned(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    write_generated_doc(project)
    invoke_json(runner, ["scan"])
    invoke_json(runner, ["document", "mark-fresh", "--all", "--allow-unlinked", "--reason", "baseline"])
    write_generated_doc(project, include_old=False)

    result = invoke_json(runner, ["scan"])
    _, record = generated_record(project)

    assert result["result"]["reconciliation"]["unlinked_sections_pruned"] == 1
    section_ids = {section["section_id"] for section in record["sections"]}
    assert "md:section:docs/generated.md::old-release" not in section_ids
    assert "md:section:docs/generated.md::keep" in section_ids
    doctor = invoke_json(runner, ["doctor"])["result"]
    assert not any(issue["code"] == "missing_section" for issue in doctor["issues"])
    assert invoke_json(runner, ["link", "audit"])["result"]["ok"] is True


def test_unchanged_scan_repairs_preexisting_unlinked_record(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    write_generated_doc(project)
    invoke_json(runner, ["scan"])
    invoke_json(runner, ["document", "mark-fresh", "--all", "--allow-unlinked", "--reason", "baseline"])
    workspace, _ = generated_record(project)
    record_path = doc_record_path(workspace, "docs/generated.md")
    payload = load_yaml(record_path)
    payload["sections"].append(
        {
            "section_id": "md:section:docs/generated.md::removed-before-upgrade",
            "doc_path": "docs/generated.md",
            "heading_path": ["Releases", "Removed before upgrade"],
            "heading_slug": "removed-before-upgrade",
            "line_span": [1, 1],
            "section_hash": "stale",
            "summary": "stale",
            "links": [],
        }
    )
    dump_yaml(record_path, payload)

    result = invoke_json(runner, ["scan"])["result"]
    _, repaired = generated_record(project)

    assert result["unchanged"] is True
    assert result["reconciliation"]["unlinked_sections_pruned"] == 1
    assert "md:section:docs/generated.md::removed-before-upgrade" not in {section["section_id"] for section in repaired["sections"]}


def test_new_section_is_added_to_existing_record(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    write_generated_doc(project, include_old=False)
    invoke_json(runner, ["scan"])
    invoke_json(runner, ["document", "mark-fresh", "--all", "--allow-unlinked", "--reason", "baseline"])
    (project / "docs" / "generated.md").write_text(
        "# Releases\n\n## Keep\n\nKeep content.\n\n## New release\n\nNew content.\n",
        encoding="utf-8",
    )

    result = invoke_json(runner, ["scan"])["result"]
    _, record = generated_record(project)
    sections = {section["section_id"]: section for section in record["sections"]}

    assert result["reconciliation"]["sections_added"] == 1
    assert sections["md:section:docs/generated.md::new-release"]["links"] == []


def test_surviving_metadata_refresh_preserves_links(project: Path, runner: CliRunner) -> None:
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
    before = load_doc_record(load_workspace(start=project), "docs/usage.md")
    (project / "docs" / "usage.md").write_text(
        "# Usage\n\nIntroductory text.\n\n"
        "<!-- docledger-section: usage-validate-ledger-state -->\n"
        "## Validate ledger state\n\nRun `documentledger doctor`.\n",
        encoding="utf-8",
    )

    result = invoke_json(runner, ["scan"])["result"]
    after = load_doc_record(load_workspace(start=project), "docs/usage.md")
    before_section = next(section for section in before["sections"] if section["links"])
    after_section = next(section for section in after["sections"] if section["links"])

    assert result["reconciliation"]["sections_refreshed"] >= 1
    assert after_section["section_id"] == before_section["section_id"]
    assert after_section["links"] == before_section["links"]
    assert after_section["line_span"] != before_section["line_span"]


def test_linked_orphan_is_retained_audited_and_repairable(project: Path, runner: CliRunner) -> None:
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
    (project / "docs" / "usage.md").write_text(
        "# Usage\n\n<!-- docledger-section: usage-run-scan -->\n## Run a scan\n\nRun scan.\n",
        encoding="utf-8",
    )
    invoke_json(runner, ["scan"])
    record = load_doc_record(load_workspace(start=project), "docs/usage.md")
    orphan = next(section for section in record["sections"] if section["links"])

    exit_code, audit = invoke_json_may_fail(runner, ["link", "audit"])
    assert exit_code == 1
    assert audit["ok"] is False
    assert audit["error"]["code"] == "link-audit-failed"
    assert audit["error"]["details"]["issues"]

    removed = invoke_json(
        runner,
        [
            "link",
            "remove-section",
            "--doc",
            "docs/usage.md",
            "--section",
            orphan["section_id"],
            "--source-unit",
            "py:function:documentledger/cli.py::doctor",
        ],
    )
    assert not any(section["links"] for section in removed["result"]["sections"] if section["section_id"] == orphan["section_id"])
    assert invoke_json(runner, ["link", "audit"])["result"]["ok"] is True
