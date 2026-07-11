from __future__ import annotations

from pathlib import Path

from documentledger.storage import load_workspace
from tests.conftest import invoke_json, snapshot_hashes, write_precision_sample


def test_read_only_cli_commands_do_not_mutate_storage(project: Path, runner) -> None:
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
    storage_dir = project / ".documentledger"
    before = snapshot_hashes(storage_dir)
    for args in (
        ["status"],
        ["doctor"],
        ["docs", "list"],
        ["docs", "sections", "--all"],
        ["docs", "affected"],
        ["docs", "stale"],
        ["links", "list"],
        ["links", "audit"],
        ["sources", "list"],
    ):
        invoke_json(runner, list(args))
    assert snapshot_hashes(storage_dir) == before


def test_load_workspace_is_read_only(project: Path, runner) -> None:
    invoke_json(runner, ["init"])
    storage_dir = project / ".documentledger"
    before = snapshot_hashes(storage_dir)
    load_workspace()
    assert snapshot_hashes(storage_dir) == before
