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


def _prepare_context(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    write_precision_sample(project)
    invoke_json(runner, ["scan"])


def test_explicit_output_write_failure_returns_structured_error_and_does_not_redirect(
    project: Path,
    runner: CliRunner,
    monkeypatch,
) -> None:
    import errno

    from ledgercore.errors import AtomicWriteError

    _prepare_context(project, runner)
    requested = project / "restricted" / "context.md"

    def fail_write(path: Path, content: str) -> None:
        try:
            raise PermissionError(errno.EACCES, "permission denied", str(path))
        except PermissionError as cause:
            raise AtomicWriteError("atomic output write failed") from cause

    monkeypatch.setattr("documentledger.commands.document.atomic_write_text", fail_write)
    exit_code, data = invoke_json_may_fail(
        runner,
        ["document", "build-context", "--bootstrap", "--out", str(requested)],
    )

    assert exit_code != 0
    assert data["ok"] is False
    error = data["error"]
    assert error["code"] == "output-write-failed"
    assert "--out -" in " ".join(error["remediation"])
    assert error["details"]["requested_path"] == str(requested)
    assert error["details"]["parent_directory"] == str(requested.parent)
    assert error["details"]["errno"] == errno.EACCES
    assert error["details"]["errno_name"] == "EACCES"
    assert not requested.exists()
    assert not (project / ".ledger" / "documentledger" / "artifacts" / "rendered" / "latest-context.md").exists()


def test_unwritable_context_parent_has_human_remediation_without_traceback(
    project: Path,
    runner: CliRunner,
    monkeypatch,
) -> None:
    _prepare_context(project, runner)
    blocked_parent = project / "blocked-output"
    real_mkdir = Path.mkdir

    def fail_parent(path: Path, *args, **kwargs):
        if path == blocked_parent:
            raise PermissionError("permission denied")
        return real_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", fail_parent)
    result = runner.invoke(
        app,
        ["document", "build-context", "--bootstrap", "--out", str(blocked_parent / "context.md")],
    )

    assert result.exit_code != 0
    assert "Unable to write document build-context output" in result.output
    assert "Omit --out" in result.output
    assert "Traceback" not in result.output
    assert not blocked_parent.exists()


def test_default_artifact_context_write_succeeds_without_temp_path_assumption(
    project: Path,
    runner: CliRunner,
) -> None:
    _prepare_context(project, runner)
    result = invoke_json(runner, ["document", "build-context", "--bootstrap"])
    output = Path(result["result"]["path"])

    assert output.is_file()
    assert "documentledger.context.v5" in output.read_text(encoding="utf-8")


def test_raw_context_stdout_has_no_json_envelope_or_status_prefix(project: Path, runner: CliRunner) -> None:
    _prepare_context(project, runner)
    result = runner.invoke(app, ["document", "build-context", "--bootstrap", "--out", "-"])

    assert result.exit_code == 0
    assert result.output.startswith("<!-- DOCUMENTLEDGER CONTEXT: COMPLETE;")
    assert "\n---\ndocumentledger_schema: documentledger.context.v5" in result.output
    assert not result.output.startswith("{")
    assert not (project / "-").exists()


def test_legacy_docs_build_context_alias_streams_raw_markdown(project: Path, runner: CliRunner) -> None:
    _prepare_context(project, runner)
    result = runner.invoke(app, ["docs", "build-context", "--bootstrap", "--out", "-"])

    assert result.exit_code == 0
    assert result.output.startswith("<!-- DOCUMENTLEDGER CONTEXT: COMPLETE;")
    assert "\n---\ndocumentledger_schema: documentledger.context.v5" in result.output
    assert not result.output.startswith("{")
    assert not (project / "-").exists()
