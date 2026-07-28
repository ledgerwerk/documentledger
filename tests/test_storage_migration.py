from __future__ import annotations

import json
import os
from pathlib import Path

import yaml
from typer.testing import CliRunner

from documentledger.cli import app


def _storage(uuid: str, *, scan_version: int = 0, index_hash: str = "") -> dict[str, object]:
    return {
        "schema_version": 5,
        "project_uuid": uuid,
        "state_version": 1,
        "last_scan_version": scan_version,
        "last_scan_source_file_count": 0,
        "last_scan_source_unit_count": 0,
        "last_scan_doc_file_count": 0,
        "last_scan_changed_source_count": 0,
        "last_scan_affected_section_count": 0,
        "last_scan_stale_doc_count": 0,
        "last_scan_unlinked_changed_source_count": 0,
        "last_scan_source_index_file": "source-index.json",
        "last_scan_source_index_hash": index_hash,
    }


def test_fresh_init_uses_schema3_project_and_cache_artifacts(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "documentledger").mkdir()
    runner = CliRunner()
    result = runner.invoke(app, ["--json", "init", "--project-name", "demo"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / ".ledger" / "ledger.toml").is_file()
    assert (tmp_path / ".ledger" / "documentledger" / "config.toml").is_file()
    assert (tmp_path / ".ledger" / "documentledger" / "data" / ".ledger-project.toml").is_file()
    assert not (tmp_path / "documentledger.toml").exists()
    assert not (tmp_path / ".documentledger").exists()
    assert not (tmp_path / ".ledger" / "documentledger" / "data" / "rendered").exists()


def test_legacy_migration_is_copy_first_and_manifest_last(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    uuid = "11111111-1111-4111-8111-111111111111"
    (tmp_path / "documentledger").mkdir()
    (tmp_path / "documentledger" / "module.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / "documentledger.toml").write_text(
        '[ledger]\ncode = "dl"\nname = "documentledger"\n\n'
        f'[project]\nname = "demo"\nuuid = "{uuid}"\n\n'
        '[storage]\ndocumentledger_dir = ".documentledger"\n\n'
        '[scan]\nsource_roots = ["documentledger"]\ndoc_roots = ["README.md"]\n'
        'source_extensions = [".py"]\ndoc_extensions = [".md"]\n\n'
        "[validation]\ncommands = []\n\n[policy]\nrequire_doc_frontmatter = false\n",
        encoding="utf-8",
    )
    data = tmp_path / ".documentledger"
    data.mkdir()
    (data / "storage.yaml").write_text(yaml.safe_dump(_storage(uuid), sort_keys=False), encoding="utf-8")
    runner = CliRunner()
    dry = runner.invoke(app, ["--json", "storage", "migrate", "--dry-run", "--plan-file", "plan.json"])
    assert dry.exit_code == 0, dry.output
    assert json.loads(dry.output)["result"]["dry_run"] is True
    applied = runner.invoke(app, ["--json", "storage", "migrate", "--plan-file", "plan.json"])
    assert applied.exit_code == 0, applied.output
    assert (tmp_path / ".ledger" / "ledger.toml").is_file()
    assert (tmp_path / ".ledger" / "documentledger" / "data" / "storage.yaml").is_file()
    assert (tmp_path / "documentledger.toml").is_file()
    assert (tmp_path / ".documentledger" / "storage.yaml").is_file()
    plan_id = json.loads(dry.output)["result"]["migration_id"]
    lock = tmp_path / ".ledger" / "migrations" / f"{plan_id}.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text('schema_version = 1\nphase = "locked"\n', encoding="utf-8")
    journal = lock.with_suffix(".toml")
    journal.write_text('schema_version = 1\nphase = "locked"\n', encoding="utf-8")
    recovered = runner.invoke(app, ["--json", "storage", "recover", "--journal", str(journal)])
    assert recovered.exit_code == 0, recovered.output
    assert json.loads(recovered.output)["result"]["recovered"] is True


def test_missing_scanned_source_index_requires_explicit_repair(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    uuid = "11111111-1111-4111-8111-111111111111"
    (tmp_path / "documentledger").mkdir()
    (tmp_path / "documentledger" / "module.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / "documentledger.toml").write_text(
        f'[project]\nuuid = "{uuid}"\n[storage]\ndocumentledger_dir = ".documentledger"\n'
        '[scan]\nsource_roots = ["documentledger"]\ndoc_roots = []\nsource_extensions = [".py"]\ndoc_extensions = []\n',
        encoding="utf-8",
    )
    data = tmp_path / ".documentledger"
    data.mkdir()
    (data / "storage.yaml").write_text(
        yaml.safe_dump(_storage(uuid, scan_version=1, index_hash="0" * 64), sort_keys=False), encoding="utf-8"
    )
    (data / "scan.yaml").write_text(
        yaml.safe_dump(
            {"schema": "documentledger.scan.v5", "version": 1, "source_hashes": {}, "source_index_hash": "0" * 64}, sort_keys=False
        ),
        encoding="utf-8",
    )
    runner = CliRunner()
    result = runner.invoke(app, ["--json", "storage", "migrate", "--dry-run"])
    assert result.exit_code == 0
    assert "source_index" in result.output
    blocked = runner.invoke(app, ["--json", "storage", "migrate", "--repair-missing-source-index"])
    assert blocked.exit_code != 0
    assert "source-index" in blocked.output


def test_migration_rejects_legacy_symlinks(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    uuid = "11111111-1111-4111-8111-111111111111"
    (tmp_path / "documentledger.toml").write_text(
        f'[project]\nuuid = "{uuid}"\n[storage]\ndocumentledger_dir = ".documentledger"\n',
        encoding="utf-8",
    )
    data = tmp_path / ".documentledger"
    data.mkdir()
    (data / "storage.yaml").write_text(yaml.safe_dump(_storage(uuid), sort_keys=False), encoding="utf-8")
    os.symlink(tmp_path, data / "bad-link")
    result = CliRunner().invoke(app, ["--json", "storage", "migrate", "--dry-run"])
    assert result.exit_code != 0
    assert "legacy-symlink-unsupported" in result.output
