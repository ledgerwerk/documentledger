from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from documentledger.impact import review_action_for
from documentledger.models import ChangedEvidence, MappingSuggestion, ReviewItem, ReviewPlan
from tests.conftest import invoke_json


def test_review_auto_links_only_exact_candidates_and_is_idempotent(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    (project / "documentledger" / "core.py").write_text("def create_report():\n    return 1\n", encoding="utf-8")
    (project / "docs").mkdir()
    (project / "docs" / "api.md").write_text(
        "## Report API\n\nUse `py:function:documentledger/core.py::create_report`.\n",
        encoding="utf-8",
    )

    first = invoke_json(runner, ["review"])["result"]
    second = invoke_json(runner, ["review"])["result"]

    assert first["schema"] == "documentledger.review.v1"
    assert first["mapping"]["auto_applied"] == 1
    assert first["mapping"]["auto_applied_edges"][0]["confidence"] == "exact"
    assert first["mapping"]["review_required"] == 0
    assert second["mapping"]["auto_applied"] == 0


def test_review_surfaces_ambiguous_symbol_candidates_without_linking_them(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    (project / "documentledger" / "first.py").write_text("def convert(value):\n    return value\n", encoding="utf-8")
    (project / "documentledger" / "second.py").write_text("def convert(value):\n    return str(value)\n", encoding="utf-8")
    (project / "docs").mkdir()
    (project / "docs" / "api.md").write_text("## Conversion\n\nUse `convert(value)` here.\n", encoding="utf-8")

    result = invoke_json(runner, ["review"])["result"]

    assert result["mapping"]["auto_applied"] == 0
    assert result["mapping"]["ambiguous_matches"] == 1
    assert result["mapping"]["ambiguous_items"][0]["evidence"] == "convert"
    assert result["mapping"]["review_required"] == 1


def test_review_reports_ignored_test_changes_without_mapping_review(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    (project / "tests").mkdir()
    test_source = project / "tests" / "test_helpers.py"
    test_source.write_text("def helper():\n    return 1\n", encoding="utf-8")
    invoke_json(runner, ["scan"])
    test_source.write_text("def helper():\n    return 2\n", encoding="utf-8")

    result = invoke_json(runner, ["review"])["result"]

    assert result["ignored_changes"] == {"test": 1}
    assert result["unmapped_relevant_total"] == 0
    assert result["state"] == "clean"


def test_review_output_bounds_default_arrays() -> None:
    evidence = ChangedEvidence("py:function:pkg.py::f", "pkg.py", ("body_hash",), "production")
    affected = tuple(
        ReviewItem("docs/api.md", f"section-{index}", "API", "review_required", "medium", (evidence,) * 100, ("Check it.",))
        for index in range(1000)
    )
    suggestions = tuple(
        MappingSuggestion(
            "docs/api.md",
            f"section-{index}",
            f"py:function:pkg.py::f{index}",
            "high",
            "api",
            "public-api",
            "Mentioned.",
            "f",
        )
        for index in range(1000)
    )
    plan = ReviewPlan(
        scan_version=3,
        state="review_required",
        affected=affected,
        unmapped_relevant=(evidence,) * 1000,
        mapping_suggestions=suggestions,
        auto_applied=(),
        ambiguous_items=(),
        ambiguous_match_count=0,
        ignored_change_counts={},
        next_action={"kind": "review_mappings", "command": "finish"},
    )

    result = plan.to_record()

    assert len(result["affected"]) == 40
    assert len(result["unmapped_relevant"]) == 40
    assert len(result["mapping"]["suggestions"]) == 40
    assert len(result["affected"][0]["changed_units"]) == 40
    assert result["affected"][0]["changed_units_omitted"] == 60
    assert result["omitted"] == {
        "affected": 960,
        "unmapped_relevant": 960,
        "suggestions": 960,
        "auto_applied_edges": 0,
        "ambiguous_items": 0,
    }


def test_review_action_classifies_public_internal_and_generated_changes() -> None:
    assert review_action_for([{"coverage": "api-autodoc", "changed_hashes": ["signature_hash"]}]) == "generated_verify"
    assert review_action_for([{"coverage": "architecture", "changed_hashes": ["body_hash"]}]) == "review_required"
    assert review_action_for([{"coverage": "api", "changed_hashes": ["signature_hash"]}]) == "update_required"
