from __future__ import annotations

from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from tests.conftest import invoke_json, invoke_json_may_fail, load_yaml, write_precision_sample


def _prepare(project: Path, runner: CliRunner, *, extra_docs: dict[str, str] | None = None) -> None:
    invoke_json(runner, ["init"])
    write_precision_sample(project)
    for relative, content in (extra_docs or {}).items():
        path = project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    invoke_json(runner, ["scan"])


def _propose(project: Path, runner: CliRunner, output_dir: Path) -> dict[str, Any]:
    return invoke_json(runner, ["link", "propose", "--all-docs", "--out-dir", str(output_dir)])["result"]


def test_nested_index_proposals_have_distinct_full_path_filenames(project: Path, runner: CliRunner) -> None:
    _prepare(
        project,
        runner,
        extra_docs={
            "docs/index.md": "# Top level\n\nSee `documentledger/cli.py`.\n",
            "docs/api/index.md": "# API\n\nSee `documentledger/cli.py`.\n",
        },
    )
    output_dir = project / "proposal-output"
    result = _propose(project, runner, output_dir)
    manifest = load_yaml(output_dir / "proposal-manifest.yaml")
    names = {entry["doc_path"]: entry["filename"] for entry in manifest["documents"]}

    assert names["docs/index.md"] != names["docs/api/index.md"]
    assert names["docs/index.md"].startswith("docs-index-md-")
    assert names["docs/api/index.md"].startswith("docs-api-index-md-")
    assert result["collisions"] == result["conflicts"] == 0
    assert result["proposal_files_written"] == result["documents_considered"]


def test_proposal_manifest_and_outputs_are_deterministic_across_runs(project: Path, runner: CliRunner) -> None:
    _prepare(project, runner)
    first_dir = project / "proposals-a"
    second_dir = project / "proposals-b"

    _propose(project, runner, first_dir)
    _propose(project, runner, second_dir)

    assert (first_dir / "proposal-manifest.yaml").read_bytes() == (second_dir / "proposal-manifest.yaml").read_bytes()
    first = {path.name: path.read_bytes() for path in first_dir.glob("*.yaml") if path.name != "proposal-manifest.yaml"}
    second = {path.name: path.read_bytes() for path in second_dir.glob("*.yaml") if path.name != "proposal-manifest.yaml"}
    assert first == second


def test_import_rejects_manifest_from_an_older_scan(project: Path, runner: CliRunner) -> None:
    _prepare(project, runner)
    output_dir = project / "proposals"
    _propose(project, runner, output_dir)
    invoke_json(runner, ["link", "import-map", "--directory", str(output_dir), "--review"])
    source = project / "documentledger" / "cli.py"
    source.write_text(source.read_text(encoding="utf-8") + "\n# changed after proposal generation\n", encoding="utf-8")
    invoke_json(runner, ["scan"])

    exit_code, data = invoke_json_may_fail(
        runner,
        ["link", "import-map", "--directory", str(output_dir), "--check-and-apply"],
    )

    assert exit_code != 0
    assert data["error"]["code"] == "proposal-manifest-stale"
    assert not (project / ".ledger" / "documentledger" / "data" / "docs").exists()


def test_directory_import_ignores_unowned_yaml_and_requires_review(project: Path, runner: CliRunner) -> None:
    _prepare(project, runner)
    output_dir = project / "proposals"
    _propose(project, runner, output_dir)
    rogue = output_dir / "personal.yaml"
    rogue.write_text("unrecognized: [invalid", encoding="utf-8")

    exit_code, pending = invoke_json_may_fail(
        runner,
        ["link", "import-map", "--directory", str(output_dir), "--check-and-apply"],
    )
    assert exit_code != 0
    assert pending["error"]["code"] == "mapping-review-required"

    invoke_json(runner, ["link", "import-map", "--directory", str(output_dir), "--review"])
    applied = invoke_json(runner, ["link", "import-map", "--directory", str(output_dir), "--check-and-apply"])["result"]
    manifest = load_yaml(output_dir / "proposal-manifest.yaml")

    assert applied["mapping_files"] == len(manifest["documents"])
    assert applied["unowned_mapping_files"] == ["personal.yaml"]
    assert applied["planned_edges"] == sum(
        len(section["links"])
        for entry in manifest["documents"]
        for section in load_yaml(output_dir / entry["filename"]).get("sections", [])
    )


def test_no_candidate_document_is_explicit_and_requires_review(project: Path, runner: CliRunner) -> None:
    _prepare(project, runner, extra_docs={"docs/no-candidate.md": "# No mapping\n\nBuild the package before use.\n"})
    output_dir = project / "proposals"
    result = _propose(project, runner, output_dir)
    manifest = load_yaml(output_dir / "proposal-manifest.yaml")
    entry = next(item for item in manifest["documents"] if item["doc_path"] == "docs/no-candidate.md")
    payload = load_yaml(output_dir / entry["filename"])

    assert "docs/no-candidate.md" in result["documents_without_candidates"]
    assert entry["outcome"] == "no_candidates"
    assert payload["sections"] == []
    assert entry["reviewed"] is False
    invoke_json(runner, ["link", "import-map", "--directory", str(output_dir), "--review"])
    applied = invoke_json(runner, ["link", "import-map", "--directory", str(output_dir), "--check-and-apply"])["result"]
    assert applied["empty_mapping_files"] >= 1


def test_proposal_replacement_never_removes_or_overwrites_unowned_files(project: Path, runner: CliRunner) -> None:
    _prepare(project, runner)
    output_dir = project / "proposals"
    _propose(project, runner, output_dir)
    personal = output_dir / "notes.yaml"
    original = b"keep this user file unchanged\n"
    personal.write_bytes(original)

    exit_code, blocked = invoke_json_may_fail(runner, ["link", "propose", "--all-docs", "--out-dir", str(output_dir)])
    assert exit_code != 0
    assert blocked["error"]["code"] == "proposal-manifest-exists"
    assert personal.read_bytes() == original

    replacement = invoke_json(
        runner,
        ["link", "propose", "--all-docs", "--out-dir", str(output_dir), "--replace-owned-proposals"],
    )["result"]
    assert personal.read_bytes() == original
    assert "notes.yaml" in replacement["unowned_files_preserved"]


def test_filename_collision_is_rejected_before_any_proposal_write(project: Path, runner: CliRunner, monkeypatch) -> None:
    _prepare(project, runner)
    output_dir = project / "collision-output"
    monkeypatch.setattr("documentledger.links.proposal_filename", lambda _: "collision.yaml")

    exit_code, data = invoke_json_may_fail(
        runner,
        ["link", "propose", "--all-docs", "--out-dir", str(output_dir)],
    )

    assert exit_code != 0
    assert data["error"]["code"] == "proposal-filename-collision"
    assert not list(output_dir.glob("*.yaml"))


def test_directory_without_manifest_never_imports_unowned_maps(project: Path, runner: CliRunner) -> None:
    _prepare(project, runner)
    directory = project / "unmanaged-maps"
    directory.mkdir()
    (directory / "manual.yaml").write_text(
        "schema: documentledger.mapping_proposal.v1\ndoc_path: docs/usage.md\nsections: []\n",
        encoding="utf-8",
    )

    exit_code, data = invoke_json_may_fail(
        runner,
        ["link", "import-map", "--directory", str(directory), "--check-and-apply"],
    )

    assert exit_code != 0
    assert data["error"]["code"] == "proposal-manifest-missing"
    assert not (project / ".ledger" / "documentledger" / "data" / "docs").exists()


def test_plural_import_alias_obeys_reviewed_manifest_selection(project: Path, runner: CliRunner) -> None:
    _prepare(project, runner)
    output_dir = project / "proposals"
    _propose(project, runner, output_dir)
    (output_dir / "unowned.yaml").write_text("not a map", encoding="utf-8")

    review = invoke_json(runner, ["links", "import-map", "--directory", str(output_dir), "--review"])
    applied = invoke_json(runner, ["links", "import-map", "--directory", str(output_dir), "--check-and-apply"])["result"]

    assert review["result"]["reviewed_files"] > 0
    assert applied["unowned_mapping_files"] == ["unowned.yaml"]


def test_source_change_without_rescan_blocks_reviewed_import(project: Path, runner: CliRunner) -> None:
    _prepare(project, runner)
    output_dir = project / "proposals"
    _propose(project, runner, output_dir)
    invoke_json(runner, ["link", "import-map", "--directory", str(output_dir), "--review"])
    source = project / "documentledger" / "cli.py"
    source.write_text(source.read_text(encoding="utf-8") + "\n# source changed\n", encoding="utf-8")

    exit_code, data = invoke_json_may_fail(
        runner,
        ["link", "import-map", "--directory", str(output_dir), "--check-and-apply"],
    )

    assert exit_code != 0
    assert data["error"]["code"] == "proposal-scan-stale"
    assert not (project / ".ledger" / "documentledger" / "data" / "docs").exists()
