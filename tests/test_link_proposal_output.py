from __future__ import annotations

import errno
from pathlib import Path

from ledgercore.errors import AtomicWriteError
from typer.testing import CliRunner

from tests.conftest import invoke_json, invoke_json_may_fail, write_precision_sample


def _prepare_proposal(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    write_precision_sample(project)
    (project / "docs" / "proposal.md").write_text(
        "# Proposal\n\n## Scan command\n\nThis documents `py:function:documentledger/cli.py::scan`.\n",
        encoding="utf-8",
    )
    invoke_json(runner, ["scan"])


def test_proposal_directory_creation_failure_is_structured(project: Path, runner: CliRunner, monkeypatch) -> None:
    _prepare_proposal(project, runner)
    output_dir = project / "restricted-proposals"
    real_mkdir = Path.mkdir

    def fail_output_dir(path: Path, *args, **kwargs):
        if path == output_dir:
            raise PermissionError(errno.EACCES, "permission denied", str(path))
        return real_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", fail_output_dir)
    exit_code, data = invoke_json_may_fail(
        runner,
        ["link", "propose", "--all-docs", "--out-dir", str(output_dir)],
    )

    assert exit_code != 0
    assert data["ok"] is False
    error = data["error"]
    assert error["code"] == "output-write-failed"
    assert Path(error["details"]["requested_path"]).parent == output_dir
    assert error["details"]["errno"] == errno.EACCES
    assert any("--out-dir" in item for item in error["remediation"])
    assert not output_dir.exists()
    assert not list((project / ".ledger" / "documentledger" / "artifacts" / "proposals").glob("*.yaml"))


def test_proposal_yaml_write_failure_is_structured_and_keeps_atomic_writer(
    project: Path,
    runner: CliRunner,
    monkeypatch,
) -> None:
    _prepare_proposal(project, runner)
    output_dir = project / "proposals"

    def fail_write(path: Path, payload, *, sort_keys: bool = False) -> None:
        try:
            raise PermissionError(errno.EACCES, "permission denied", str(path))
        except PermissionError as cause:
            raise AtomicWriteError("atomic yaml write failed") from cause

    monkeypatch.setattr("documentledger.links.core_write_yaml", fail_write)
    exit_code, data = invoke_json_may_fail(
        runner,
        ["link", "propose", "--all-docs", "--out-dir", str(output_dir)],
    )

    assert exit_code != 0
    assert data["ok"] is False
    error = data["error"]
    assert error["code"] == "output-write-failed"
    assert error["details"]["root_cause_category"] == "PermissionError"
    assert error["details"]["errno_name"] == "EACCES"
    assert "Omit --out-dir" in " ".join(error["remediation"])
    assert not list(output_dir.glob("*.yaml"))


def test_default_artifact_proposal_write_failure_mentions_artifacts_mount(
    project: Path,
    runner: CliRunner,
    monkeypatch,
) -> None:
    _prepare_proposal(project, runner)

    def fail_write(path: Path, payload, *, sort_keys: bool = False) -> None:
        raise PermissionError(errno.EACCES, "permission denied", str(path))

    monkeypatch.setattr("documentledger.links.core_write_yaml", fail_write)
    exit_code, data = invoke_json_may_fail(runner, ["link", "propose", "--all-docs"])

    assert exit_code != 0
    assert data["error"]["code"] == "output-write-failed"
    assert data["error"]["details"]["output_location"] == "configured_artifacts_mount"
    assert any("artifacts mount" in item for item in data["error"]["remediation"])
