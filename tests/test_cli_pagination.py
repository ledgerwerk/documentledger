from __future__ import annotations

from documentledger.cli import app
from tests.conftest import invoke_json, write_precision_sample


def test_sources_list_filters_and_omits_hashes_by_default(project, runner) -> None:
    invoke_json(runner, ["init"])
    write_precision_sample(project)
    invoke_json(runner, ["scan"])
    data = invoke_json(runner, ["source", "list", "--kind", "function", "--path-prefix", "documentledger"])["result"]["sources"]
    assert data
    assert all("hashes" not in item for item in data)
    assert all(item["kind"] == "function" for item in data)


def test_sources_list_ids_only_and_cursor(project, runner) -> None:
    invoke_json(runner, ["init"])
    write_precision_sample(project)
    invoke_json(runner, ["scan"])
    first = invoke_json(runner, ["source", "list", "--ids-only", "--limit", "1"])["result"]
    second = invoke_json(runner, ["source", "list", "--ids-only", "--limit", "1", "--cursor", str(first["next_cursor"])])["result"]
    assert len(first["sources"]) == 1
    assert len(second["sources"]) == 1
    assert first["sources"][0] != second["sources"][0]


def test_docs_sections_outline_is_compact(project, runner) -> None:
    invoke_json(runner, ["init"])
    write_precision_sample(project)
    data = invoke_json(runner, ["document", "sections", "--doc", "docs/usage.md", "--outline"])["result"]["docs"][0]["sections"]
    assert data
    assert set(data[0]) == {"section_id", "doc_path", "heading_path", "heading_slug", "line_span"}


def test_invalid_cursor_returns_structured_error(project, runner) -> None:
    invoke_json(runner, ["init"])
    result = runner.invoke(app, ["--json", "source", "list", "--cursor", "oops"])
    assert result.exit_code != 0
    assert "invalid-cursor" in result.output
