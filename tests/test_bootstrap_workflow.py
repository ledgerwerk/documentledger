from __future__ import annotations

from pathlib import Path

from tests.conftest import invoke_json, load_yaml


def test_documented_bootstrap_workflow_is_executable(project: Path, runner) -> None:
    demo = project / "demo"
    tests = project / "tests"
    docs = project / "docs"
    demo.mkdir()
    tests.mkdir()
    docs.mkdir()
    (demo / "__init__.py").write_text("\n", encoding="utf-8")
    (demo / "service.py").write_text(
        "class Service:\n    def run(self, value: str) -> str:\n        return value\n",
        encoding="utf-8",
    )
    (demo / "cli.py").write_text("def main() -> int:\n    return 0\n", encoding="utf-8")
    (tests / "test_service.py").write_text("def build() -> None:\n    pass\n", encoding="utf-8")
    (project / "README.md").write_text(
        "# Demo\n\nUse `demo/service.py` and `Service.run`.\n\nBuild the package before use.\n",
        encoding="utf-8",
    )
    (docs / "index.md").write_text("# Demo docs\n\nSee `demo/service.py`.\n", encoding="utf-8")
    (docs / "architecture.md").write_text("# Architecture\n\nThe service is intentionally documented separately.\n", encoding="utf-8")

    invoke_json(runner, ["init"])
    config = project / ".ledger" / "documentledger" / "config.toml"
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            'source_roots = ["documentledger", "tests"]',
            'source_roots = ["demo", "tests"]',
        ),
        encoding="utf-8",
    )

    assert invoke_json(runner, ["status"])["ok"] is True
    assert invoke_json(runner, ["doctor"])["result"]["ok"] is True
    scan = invoke_json(runner, ["scan"])
    assert scan["result"]["version"] == 1

    context_path = project / "bootstrap.md"
    context = runner.invoke(
        __import__("documentledger.cli").cli.app,
        ["document", "build-context", "--bootstrap", "--out", str(context_path)],
    )
    assert context.exit_code == 0
    context_text = context_path.read_text(encoding="utf-8")
    assert "documentledger.context.v5" in context_text
    assert "Service" in context_text
    assert "run(self, value: str) -> str" in context_text

    maps = project / "maps"
    proposals = runner.invoke(
        __import__("documentledger.cli").cli.app,
        ["link", "propose", "--all-docs", "--out-dir", str(maps)],
    )
    assert proposals.exit_code == 0
    (maps / "reviewed-noop.yaml").write_text(
        "schema: documentledger.mapping_proposal.v1\ndoc_path: docs/architecture.md\nsections: []\n",
        encoding="utf-8",
    )
    applied = invoke_json(runner, ["link", "import-map", "--directory", str(maps), "--check-and-apply"])
    assert applied["result"]["empty_mapping_files"] == 1
    assert invoke_json(runner, ["link", "audit"])["result"]["ok"] is True
    coverage = invoke_json(runner, ["coverage"])["result"]
    assert coverage["documents"]["total"] == 3

    assert invoke_json(runner, ["check"])["result"]["ok"] is True
    fresh = invoke_json(
        runner,
        [
            "document",
            "mark-fresh",
            "--all",
            "--allow-unlinked",
            "--reason",
            "Bootstrap documentation completed after scan version 1.",
        ],
    )
    assert set(fresh["result"]["selected_docs"]) == {"README.md", "docs/architecture.md", "docs/index.md"}
    final_status = invoke_json(runner, ["status"])["result"]
    assert final_status["freshness_state"] == "clean"
    assert final_status["coverage_review_required"] is False

    proposal_sources = {
        str(link["source_unit"])
        for path in maps.glob("*.yaml")
        for section in load_yaml(path).get("sections", [])
        for link in section.get("links", [])
    }
    assert not any("tests/test_service.py" in source_id for source_id in proposal_sources)
