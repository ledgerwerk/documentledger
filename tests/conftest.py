from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from documentledger.cli import app


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "documentledger").mkdir()
    (tmp_path / "documentledger" / "cli.py").write_text("print('hello')\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# docs\n", encoding="utf-8")
    return tmp_path


def invoke_json(runner: CliRunner, args: list[str]) -> dict[str, object]:
    result = runner.invoke(app, ["--json", *args])
    assert result.exit_code == 0, result.output
    return json.loads(result.output)
