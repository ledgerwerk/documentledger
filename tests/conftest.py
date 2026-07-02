from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from documentledger.cli import app

FORBIDDEN_TIMESTAMP_KEYS = {f"{prefix}_at" for prefix in ("created", "updated", "generated")}


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


def load_yaml(path: Path) -> dict[str, object]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    assert isinstance(data, dict)
    return data


def dump_yaml(path: Path, payload: dict[str, object]) -> None:
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def write_precision_sample(project: Path) -> None:
    (project / "docs").mkdir(exist_ok=True)
    (project / "documentledger" / "cli.py").write_text(
        "import typer\n"
        "app = typer.Typer()\n\n"
        "@app.command()\n"
        "def doctor(ctx: typer.Context) -> None:\n"
        '    print("doctor")\n\n'
        "@app.command()\n"
        "def scan(ctx: typer.Context) -> None:\n"
        '    print("scan")\n',
        encoding="utf-8",
    )
    (project / "docs" / "usage.md").write_text(
        "# Usage\n\n"
        "<!-- docledger-section: usage-run-scan -->\n"
        "## Run a scan\n\n"
        "Run `docledger scan`.\n\n"
        "<!-- docledger-section: usage-validate-ledger-state -->\n"
        "## Validate ledger state\n\n"
        "Run `docledger doctor`.\n",
        encoding="utf-8",
    )


def assert_no_timestamp_keys(value: object) -> None:
    if isinstance(value, dict):
        assert not (FORBIDDEN_TIMESTAMP_KEYS & set(value)), value
        for child in value.values():
            assert_no_timestamp_keys(child)
    elif isinstance(value, list):
        for child in value:
            assert_no_timestamp_keys(child)
