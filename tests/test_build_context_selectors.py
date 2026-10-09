from __future__ import annotations

from pathlib import Path

from documentledger.cli import app
from tests.conftest import invoke_json, invoke_json_may_fail, write_precision_sample


def prepare_stale_section(project: Path, runner) -> None:
    invoke_json(runner, ["init"])
    write_precision_sample(project)
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
    invoke_json(runner, ["scan"])


def test_build_context_affected_mode(project: Path, runner) -> None:
    prepare_stale_section(project, runner)
    data = invoke_json(runner, ["document", "build-context", "--affected"])
    assert data["result"]["mode"] == "affected"
    assert data["result"]["sections"] == 1


def test_build_context_doc_mode_and_section_selector(project: Path, runner) -> None:
    invoke_json(runner, ["init"])
    write_precision_sample(project)
    data = invoke_json(runner, ["document", "build-context", "--doc", "docs/usage.md", "--section", "usage-run-scan"])
    assert data["result"]["mode"] == "doc"
    assert data["result"]["sections"] == 1


def test_build_context_bootstrap_mode(project: Path, runner) -> None:
    invoke_json(runner, ["init"])
    invoke_json(runner, ["scan"])
    data = invoke_json(runner, ["document", "build-context", "--bootstrap"])
    assert data["result"]["mode"] == "bootstrap"
    assert data["result"]["path"]


def test_build_context_requires_doc_for_section(project: Path, runner) -> None:
    invoke_json(runner, ["init"])
    result = runner.invoke(app, ["--json", "document", "build-context", "--section", "usage-run-scan"])
    assert result.exit_code != 0
    assert "doc-required" in result.output


def test_build_context_reports_truncation(project: Path, runner) -> None:
    prepare_stale_section(project, runner)
    data = invoke_json(runner, ["document", "build-context", "--affected", "--max-bytes", "1500"])
    assert data["result"]["truncated"] is True
    assert data["result"]["bytes"] <= 1500
    assert data["result"]["omitted"]
    assert data["result"]["next_cursor"]


def _prepare_bootstrap_context(project: Path, runner) -> None:
    invoke_json(runner, ["init"])
    write_precision_sample(project)
    invoke_json(runner, ["scan"])


def test_bootstrap_context_pages_resume_with_checksums_and_raw_banner(project: Path, runner) -> None:
    _prepare_bootstrap_context(project, runner)
    all_unit_ids: list[str] = []
    cursor: str | None = None
    first_cursor: str | None = None
    scan_version: int | None = None

    for page_number in range(10):
        output_path = project / f"context-page-{page_number}.md"
        args = ["document", "build-context", "--bootstrap", "--page-size", "1", "--out", str(output_path)]
        if cursor:
            args.extend(["--cursor", cursor])
        result = invoke_json(runner, args)["result"]
        content = output_path.read_text(encoding="utf-8")
        if scan_version is None:
            scan_version = result["scan_version"]
        assert result["scan_version"] == scan_version

        assert result["bytes"] == len(content.encode("utf-8"))
        assert result["emitted_units"] == len(result["emitted_unit_ids"])
        assert len(result["unit_checksums"]) == result["emitted_units"]
        assert all(len(checksum["sha256"]) == 64 for checksum in result["unit_checksums"])
        assert content.startswith("<!-- DOCUMENTLEDGER CONTEXT: ")
        all_unit_ids.extend(result["emitted_unit_ids"])
        if page_number == 0:
            assert result["truncated"] is True
            assert result["omitted"]
            first_cursor = result["next_cursor"]
            assert first_cursor
            repeat_path = project / "context-page-repeat.md"
            repeat_args = ["document", "build-context", "--bootstrap", "--page-size", "1", "--out", str(repeat_path)]
            repeated = invoke_json(runner, repeat_args)["result"]
            assert repeated["emitted_unit_ids"] == result["emitted_unit_ids"]
            assert repeated["unit_checksums"] == result["unit_checksums"]
            assert repeated["next_cursor"] == first_cursor
            assert repeat_path.read_text(encoding="utf-8") == content
        cursor = result["next_cursor"]
        if cursor is None:
            assert "<!-- DOCUMENTLEDGER CONTEXT: COMPLETE;" in content
            break
        assert "<!-- DOCUMENTLEDGER CONTEXT: INCOMPLETE;" in content
    else:
        raise AssertionError("context paging did not complete within ten pages")

    assert len(all_unit_ids) == len(set(all_unit_ids))
    assert len(all_unit_ids) == result["total_units"]

    raw = runner.invoke(app, ["document", "build-context", "--bootstrap", "--page-size", "1", "--out", "-"])
    assert raw.exit_code == 0
    assert raw.output.startswith("<!-- DOCUMENTLEDGER CONTEXT: INCOMPLETE;")
    assert first_cursor is not None


def test_context_cursor_rejects_changed_evidence_and_strict_writes_nothing(project: Path, runner) -> None:
    _prepare_bootstrap_context(project, runner)
    first_path = project / "first-page.md"
    first = invoke_json(
        runner,
        ["document", "build-context", "--bootstrap", "--page-size", "1", "--out", str(first_path)],
    )["result"]
    cursor = first["next_cursor"]
    assert cursor

    source = project / "documentledger" / "cli.py"
    source.write_text(source.read_text(encoding="utf-8") + "\n# changed after context page\n", encoding="utf-8")
    exit_code, error = invoke_json_may_fail(
        runner,
        ["document", "build-context", "--bootstrap", "--page-size", "1", "--cursor", cursor],
    )
    assert exit_code != 0
    assert error["error"]["code"] == "context-cursor-stale"

    strict_output = project / "strict-context.md"
    exit_code, error = invoke_json_may_fail(
        runner,
        [
            "document",
            "build-context",
            "--bootstrap",
            "--page-size",
            "1",
            "--strict",
            "--out",
            str(strict_output),
        ],
    )
    assert exit_code != 0
    assert error["error"]["code"] == "context-incomplete"
    assert not strict_output.exists()
