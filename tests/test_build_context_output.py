from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from documentledger.cli import app
from tests.conftest import invoke_json, invoke_json_may_fail, write_precision_sample


def test_out_dash_streams_without_creating_artifacts(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    write_precision_sample(project)
    invoke_json(runner, ["scan"])

    result = runner.invoke(app, ["document", "build-context", "--bootstrap", "--out", "-"])

    assert result.exit_code == 0
    assert "documentledger.context.v5" in result.output
    assert not (project / "-").exists()
    assert not (project / ".ledger" / "documentledger" / "artifacts" / "rendered" / "latest-context.md").exists()


def test_regular_out_path_remains_durable(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    write_precision_sample(project)
    invoke_json(runner, ["scan"])
    output = project / "ctx.md"

    result = runner.invoke(app, ["document", "build-context", "--bootstrap", "--out", str(output)])

    assert result.exit_code == 0
    assert output.exists()
    assert "documentledger.context.v5" in output.read_text(encoding="utf-8")


def test_special_stdout_path_is_rejected_with_remediation(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    write_precision_sample(project)
    invoke_json(runner, ["scan"])

    result = runner.invoke(app, ["document", "build-context", "--bootstrap", "--out", "/dev/stdout"])

    assert result.exit_code != 0
    assert "--out -" in result.output


def test_json_stdout_and_print_modes_are_never_mixed(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    write_precision_sample(project)
    invoke_json(runner, ["scan"])

    for args in (
        ["document", "build-context", "--bootstrap", "--out", "-"],
        ["document", "build-context", "--bootstrap", "--print"],
    ):
        exit_code, data = invoke_json_may_fail(runner, args)
        assert exit_code != 0
        assert data["ok"] is False
        assert data["error"]["code"] in {"stdout-json-conflict", "invalid-option-combination"}
        json.dumps(data)
