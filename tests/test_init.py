from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from documentledger.cli import app
from documentledger.config import load_tool_config_v2
from documentledger.storage import load_config
from tests.conftest import assert_no_timestamp_keys, invoke_json, load_yaml


def test_init_creates_config_and_storage(project: Path, runner: CliRunner) -> None:
    data = invoke_json(runner, ["init", "--project-name", "demo"])
    assert data["ok"] is True
    assert (project / ".ledger" / "ledger.toml").exists()
    assert (project / ".ledger" / "documentledger" / "config.toml").exists()
    assert (project / ".ledger" / "documentledger" / "data" / "storage.yaml").exists()
    assert (project / ".ledger" / "documentledger" / "data" / "docs").is_dir() is False
    storage = load_yaml(project / ".ledger" / "documentledger" / "data" / "storage.yaml")
    assert storage["schema_version"] == 5
    assert storage["state_version"] == 1
    assert "next_scan_number" not in storage
    assert "last_scan_id" not in storage
    assert_no_timestamp_keys(storage)


def test_legacy_init_options_are_rejected(project: Path, runner: CliRunner) -> None:
    result = runner.invoke(app, ["--json", "init", "--hidden-config"])
    assert result.exit_code != 0
    assert "legacy-init-options-unsupported" in result.output


def test_default_legacy_compatible_config_uses_canonical_storage(tmp_path: Path) -> None:
    config_path = tmp_path / "documentledger.toml"
    config_path.write_text('[project]\nname = "demo"\n', encoding="utf-8")

    config = load_config(config_path)

    assert config.storage_dir == tmp_path / ".ledger"


def test_reinitialization_fails_cleanly(project: Path, runner: CliRunner) -> None:
    invoke_json(runner, ["init"])
    result = runner.invoke(app, ["--json", "init"])
    assert result.exit_code != 0
    assert "already-initialized" in result.output


def test_external_storage_option_is_rejected(project: Path, runner: CliRunner) -> None:
    result = runner.invoke(app, ["--json", "init", "--documentledger-dir", "../ledger-state"])
    assert result.exit_code != 0
    assert "legacy-init-options-unsupported" in result.output


def _write_package_project(root: Path, package: str, *, src_layout: bool = False) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "{package.replace("_", "-")}"\n',
        encoding="utf-8",
    )
    package_root = root / ("src/" if src_layout else "") / package
    package_root.mkdir(parents=True)
    (package_root / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    (package_root / "api.py").write_text("def public_api() -> int:\n    return 1\n", encoding="utf-8")
    return package_root


def test_init_audioexport_detects_package_and_tests_roots(tmp_path: Path, runner: CliRunner, monkeypatch) -> None:
    _write_package_project(tmp_path, "audioexport")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_api.py").write_text("def test_api(): pass\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    data = invoke_json(runner, ["init"])
    config = load_tool_config_v2(tmp_path / ".ledger" / "documentledger" / "config.toml")

    assert config.source_roots == ("audioexport", "tests")
    discovery = data["result"]["source_root_discovery"]
    assert discovery["production_roots"] == ["audioexport"]
    assert discovery["test_roots"] == ["tests"]
    assert discovery["source_file_counts"] == {"audioexport": 2, "tests": 1}
    assert discovery["confidence"] == "high"
    assert "metadata" in discovery["reason"]


def test_init_src_layout_detects_package_root(tmp_path: Path, runner: CliRunner, monkeypatch) -> None:
    _write_package_project(tmp_path, "audioexport", src_layout=True)
    monkeypatch.chdir(tmp_path)

    data = invoke_json(runner, ["init"])
    config = load_tool_config_v2(tmp_path / ".ledger" / "documentledger" / "config.toml")

    assert config.source_roots == ("src/audioexport",)
    assert data["result"]["source_root_discovery"]["source_file_counts"] == {"src/audioexport": 2}


def test_ambiguous_multi_package_init_requires_explicit_source_root(tmp_path: Path, runner: CliRunner, monkeypatch) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "sample-distribution"\n', encoding="utf-8")
    for package in ("core_a", "core_b"):
        package_root = tmp_path / package
        package_root.mkdir()
        (package_root / "__init__.py").write_text("\n", encoding="utf-8")
        (package_root / "api.py").write_text("VALUE = 1\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    failed = runner.invoke(app, ["--json", "init"])
    assert failed.exit_code != 0
    assert "source-root-ambiguous" in failed.output
    assert not (tmp_path / ".ledger" / "ledger.toml").exists()

    accepted = invoke_json(runner, ["init", "--source-root", "core_a"])
    config = load_tool_config_v2(tmp_path / ".ledger" / "documentledger" / "config.toml")
    assert config.source_roots == ("core_a",)
    assert accepted["result"]["source_root_discovery"]["confidence"] == "explicit"


def test_self_hosted_documentledger_keeps_its_package_root(tmp_path: Path, runner: CliRunner, monkeypatch) -> None:
    _write_package_project(tmp_path, "documentledger")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_init.py").write_text("def test_init(): pass\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    invoke_json(runner, ["init"])
    config = load_tool_config_v2(tmp_path / ".ledger" / "documentledger" / "config.toml")
    assert config.source_roots == ("documentledger", "tests")


def test_existing_project_source_config_is_not_overwritten(tmp_path: Path, runner: CliRunner, monkeypatch) -> None:
    _write_package_project(tmp_path, "audioexport")
    monkeypatch.chdir(tmp_path)
    invoke_json(runner, ["init"])
    config_path = tmp_path / ".ledger" / "documentledger" / "config.toml"
    before = config_path.read_bytes()
    (tmp_path / "later_package").mkdir()
    (tmp_path / "later_package" / "__init__.py").write_text("\n", encoding="utf-8")

    failed = runner.invoke(app, ["--json", "init"])

    assert failed.exit_code != 0
    assert "already-initialized" in failed.output
    assert config_path.read_bytes() == before


def test_doctor_reports_exact_package_root_remediation(tmp_path: Path, runner: CliRunner, monkeypatch) -> None:
    _write_package_project(tmp_path, "audioexport")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_api.py").write_text("def test_api(): pass\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    invoke_json(runner, ["init", "--source-root", "tests"])

    doctor = invoke_json(runner, ["doctor"])["result"]
    issue = next(issue for issue in doctor["issues"] if issue["code"] == "package_root_not_configured")

    assert doctor["ok"] is False
    assert "audioexport" in issue["message"]
    assert issue["remediation"] == 'Set [scan].source_roots to ["audioexport", "tests"] after reviewing the detected Python roots.'


def test_init_preserves_other_canonical_ledger_registration(tmp_path: Path, runner: CliRunner, monkeypatch) -> None:
    import ledgercore
    from ledgercore.manifest import LedgerProjectManifest, LedgerRegistration, MountDefinition

    _write_package_project(tmp_path, "audioexport")
    manifest_path = tmp_path / ".ledger" / "ledger.toml"
    manifest_path.parent.mkdir(parents=True)
    other = LedgerRegistration(
        name="otherledger",
        mounts={"state": MountDefinition(name="state", storage="project")},
    )
    original = LedgerProjectManifest(
        schema_version=3,
        project_uuid="11111111-1111-4111-8111-111111111111",
        project_name="workspace-label",
        ledgers={"otherledger": other},
    )
    ledgercore.write_ledger_manifest(manifest_path, original)
    monkeypatch.chdir(tmp_path)

    invoke_json(runner, ["init"])
    loaded = ledgercore.load_ledger_project(tmp_path)

    assert set(loaded.manifest.ledgers) == {"otherledger", "documentledger"}
    assert loaded.manifest.ledgers["otherledger"] == other
    assert loaded.manifest.project_uuid == original.project_uuid


def test_legacy_defaults_do_not_inject_documentledger_source_root(tmp_path: Path) -> None:
    config_path = tmp_path / "documentledger.toml"
    config_path.write_text('[project]\nname = "audioexport"\n', encoding="utf-8")

    assert load_config(config_path).source_roots == []


def test_legacy_init_discovers_project_package_roots(tmp_path: Path, monkeypatch) -> None:
    _write_package_project(tmp_path, "audioexport")
    monkeypatch.chdir(tmp_path)
    from documentledger.storage import init_workspace

    workspace = init_workspace(None)

    assert workspace.config.source_roots == ["audioexport"]
