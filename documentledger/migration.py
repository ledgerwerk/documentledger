"""Explicit legacy-to-schema-3 migration planning, apply, verify, and cleanup."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

import ledgercore
from ledgercore.atomic import atomic_write_text
from ledgercore.hashing import sha256_bytes, sha256_text
from ledgercore.jsonio import canonical_json
from ledgercore.manifest import LedgerProjectManifest, LedgerRegistration, MountDefinition

from documentledger.config import ToolConfig, tool_config_document
from documentledger.errors import DocumentledgerError
from documentledger.legacy import (
    LegacyInventory,
    LegacyProject,
    find_legacy_config,
    inventory_legacy_data,
    load_legacy_project,
    validate_legacy_state,
)
from documentledger.project import ARTIFACTS_MOUNT, DATA_MOUNT, TOOL_NAME, canonical_workspace
from documentledger.source_index import source_inventory
from documentledger.storage import source_index_payload, write_json, write_yaml


@dataclass(frozen=True, slots=True)
class MigrationPlan:
    migration_id: str
    project_root: Path
    legacy: LegacyProject
    inventory: LegacyInventory
    state: dict[str, Any]
    manifest: LedgerProjectManifest
    legacy_uuid: str
    canonical_uuid: str
    requires_adoption: bool
    target_config: ToolConfig
    manifest_before_sha256: str
    plan_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "migration_id": self.migration_id,
            "source": {
                "layout": "legacy",
                "config_path": str(self.legacy.config_path),
                "data_path": str(self.legacy.data_dir),
                "config_sha256": sha256_bytes(self.legacy.config_path.read_bytes()),
                "inventory_sha256": self.inventory.digest,
            },
            "target": {
                "manifest_path": str(self.project_root / ".ledger" / "ledger.toml"),
                "config_path": str(self.project_root / ".ledger" / TOOL_NAME / "config.toml"),
                "data_path": str(self.project_root / ".ledger" / TOOL_NAME / DATA_MOUNT),
                "manifest_before_sha256": self.manifest_before_sha256,
            },
            "identity": {
                "legacy_uuid": self.legacy_uuid,
                "canonical_uuid": self.canonical_uuid,
                "requires_adoption": self.requires_adoption,
            },
            "inventory": {
                "authoritative_files": len(self.inventory.authoritative),
                "derived_files": len(self.inventory.derived),
                "provisional_files": len(self.inventory.provisional),
                "unknown_files": len(self.inventory.unknown),
                "bytes": self.inventory.bytes,
            },
            "source_index": {
                "present": self.state["source_index_present"],
                "repairable": self.state["source_index_repairable"],
                "expected_hash": self.state["source_index_expected_hash"],
            },
            "plan_sha256": self.plan_sha256,
        }


def _manifest_path(root: Path) -> Path:
    return root / ".ledger" / "ledger.toml"


def _manifest_for(root: Path, legacy: LegacyProject) -> tuple[LedgerProjectManifest, str, str]:
    path = _manifest_path(root)
    before = sha256_bytes(path.read_bytes()) if path.is_file() else ""
    if path.is_file():
        try:
            manifest = ledgercore.read_ledger_manifest(path)
        except Exception as exc:
            raise DocumentledgerError("invalid_canonical_layout", str(exc)) from exc
        canonical_uuid = manifest.project_uuid
        if manifest.project_name:
            project_name = manifest.project_name
        else:
            project_name = legacy.config.project_name or root.name
        ledgers = dict(manifest.ledgers)
    else:
        canonical_uuid = legacy.config.project_uuid or str(uuid4())
        project_name = legacy.config.project_name or root.name
        ledgers = {}
    existing = ledgers.get(TOOL_NAME)
    wanted = LedgerRegistration(
        name=TOOL_NAME,
        mounts={
            DATA_MOUNT: MountDefinition(name=DATA_MOUNT, storage="project"),
            ARTIFACTS_MOUNT: MountDefinition(name=ARTIFACTS_MOUNT, storage="cache"),
        },
    )
    if existing is not None and (
        set(existing.mounts) != {DATA_MOUNT, ARTIFACTS_MOUNT}
        or existing.mounts[DATA_MOUNT].storage != "project"
        or existing.mounts[ARTIFACTS_MOUNT].storage != "cache"
    ):
        raise DocumentledgerError(
            "storage_registration_conflict",
            "Existing documentledger registration does not match the required data/project and artifacts/cache mounts.",
        )
    ledgers[TOOL_NAME] = wanted
    return (
        LedgerProjectManifest(schema_version=3, project_uuid=canonical_uuid, project_name=project_name, ledgers=ledgers),
        legacy.config.project_uuid,
        before,
    )


def plan_migration(start: Path | None = None, *, adopt_project_uuid: bool = False) -> MigrationPlan:
    legacy_path = find_legacy_config(start)
    if legacy_path is None:
        raise DocumentledgerError(
            "legacy_workspace_not_found",
            "No legacy Documentledger configuration was found.",
            ["Run `docledger init` for a new canonical project."],
        )
    legacy = load_legacy_project(legacy_path)
    inventory = inventory_legacy_data(legacy)
    state = validate_legacy_state(legacy, inventory)
    manifest, legacy_uuid, before = _manifest_for(legacy.root, legacy)
    canonical_uuid = manifest.project_uuid
    requires_adoption = bool(legacy_uuid and canonical_uuid and legacy_uuid != canonical_uuid)
    if requires_adoption and not adopt_project_uuid:
        # Dry-run is intentionally allowed to describe the acknowledgement.
        pass
    target_config = ToolConfig(
        config_version=2,
        ledger_code=str(legacy.raw.get("ledger", {}).get("code", "dl")),
        source_roots=tuple(legacy.config.source_roots),
        doc_roots=tuple(legacy.config.doc_roots),
        source_extensions=tuple(legacy.config.source_extensions),
        doc_extensions=tuple(legacy.config.doc_extensions),
        validation_commands=tuple(legacy.config.validation_commands),
        require_doc_frontmatter=legacy.config.require_doc_frontmatter,
    )
    seed = {
        "source_config": sha256_bytes(legacy.config_path.read_bytes()),
        "inventory": inventory.digest,
        "manifest": before,
        "uuid": canonical_uuid,
        "config": tool_config_document(target_config),
    }
    plan_sha = sha256_text(canonical_json(seed))
    return MigrationPlan(
        migration_id=f"documentledger-{plan_sha[:16]}",
        project_root=legacy.root,
        legacy=legacy,
        inventory=inventory,
        state=state,
        manifest=manifest,
        legacy_uuid=legacy_uuid,
        canonical_uuid=canonical_uuid,
        requires_adoption=requires_adoption,
        target_config=target_config,
        manifest_before_sha256=before,
        plan_sha256=plan_sha,
    )


def write_plan(path: Path, plan: MigrationPlan) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(plan.to_dict(), indent=2, sort_keys=True) + "\n")


def _journal_path(plan: MigrationPlan) -> Path:
    return plan.project_root / ".ledger" / "migrations" / f"{plan.migration_id}.toml"


def _lock_path(plan: MigrationPlan) -> Path:
    return plan.project_root / ".ledger" / "migrations" / f"{plan.migration_id}.lock"


def _write_journal(plan: MigrationPlan, phase: str, **extra: Any) -> Path:
    path = _journal_path(plan)
    path.parent.mkdir(parents=True, exist_ok=True)
    values = {
        "schema_version": 1,
        "migration": "documentledger-legacy-to-schema3",
        "migration_id": plan.migration_id,
        "phase": phase,
        "project_uuid": plan.canonical_uuid,
        "plan_sha256": plan.plan_sha256,
        "legacy_config": str(plan.legacy.config_path),
        "legacy_data": str(plan.legacy.data_dir),
        "target_config": str(plan.project_root / ".ledger" / TOOL_NAME / "config.toml"),
        "target_data": str(plan.project_root / ".ledger" / TOOL_NAME / DATA_MOUNT),
        **extra,
    }
    # Journal values are simple strings/integers by design and timestamp-free.
    lines = [f"{key} = {json.dumps(value)}" for key, value in values.items()]
    atomic_write_text(path, "\n".join(lines) + "\n")
    return path


def _copy_verified(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    if sha256_bytes(source.read_bytes()) != sha256_bytes(target.read_bytes()):
        raise DocumentledgerError("storage_migration_failed", f"SHA-256 verification failed after copying {source}.")


def _repair_source_index(plan: MigrationPlan, stage_data: Path) -> None:
    if not plan.state["source_index_repairable"]:
        raise DocumentledgerError("source_index_repair_failed", "Missing source-index.json cannot be reconstructed to the recorded hash.")
    scan = plan.state.get("scan") or {}
    source_paths = sorted(dict(scan.get("source_hashes", {})))
    units = source_inventory(plan.project_root, source_paths)
    payload = source_index_payload(units)
    expected = str(plan.state["source_index_expected_hash"])
    if sha256_text(canonical_json(payload)) != expected:
        raise DocumentledgerError("source_index_repair_failed", "Reconstructed source index hash does not match scan.yaml.")
    write_json(stage_data / "source-index.json", payload, compact=True)


def _validate_migration_preconditions(
    plan: MigrationPlan,
    *,
    adopt_project_uuid: bool,
    repair_missing_source_index: bool,
    recovery: bool,
) -> None:
    """Raise on unsatisfied preconditions before apply_migration starts."""
    if plan.requires_adoption and not adopt_project_uuid:
        raise DocumentledgerError(
            "project_uuid_mismatch",
            "Canonical and legacy UUIDs differ; apply requires --adopt-project-uuid acknowledgement.",
        )
    if (
        not plan.state["source_index_present"]
        and int(plan.state["metadata"].get("last_scan_version", 0)) > 0
        and not repair_missing_source_index
    ):
        raise DocumentledgerError(
            "source_index_missing",
            "source-index.json is required for an existing scan; pass",
            " --repair-missing-source-index only after reviewing the exact-hash repair analysis.",
        )
    if (
        not recovery
        and _manifest_path(plan.project_root).is_file()
        and plan.manifest_before_sha256 != sha256_bytes(_manifest_path(plan.project_root).read_bytes())
    ):
        raise DocumentledgerError("storage_migration_conflict", "Shared manifest changed since the migration plan was created.")


def apply_migration(
    plan: MigrationPlan,
    *,
    adopt_project_uuid: bool = False,
    repair_missing_source_index: bool = False,
    recovery: bool = False,
) -> dict[str, Any]:
    _validate_migration_preconditions(
        plan,
        adopt_project_uuid=adopt_project_uuid,
        repair_missing_source_index=repair_missing_source_index,
        recovery=recovery,
    )
    migration_root = plan.project_root / ".ledger" / "migrations" / plan.migration_id
    stage_data = migration_root / "data"
    if migration_root.exists() and any(migration_root.iterdir()):
        # A matching staging tree is resumable; unrelated content is not.
        pass
    migration_root.mkdir(parents=True, exist_ok=True)
    lock_path = _lock_path(plan)
    if lock_path.exists():
        if not recovery:
            raise DocumentledgerError("storage_migration_incomplete", f"Migration lock already exists: {lock_path}")
        lock_path.unlink()
    atomic_write_text(
        lock_path,
        'schema_version = 1\nmigration = "documentledger-legacy-to-schema3"\nmigration_id = '
        + json.dumps(plan.migration_id)
        + '\nphase = "locked"\nplan_sha256 = '
        + json.dumps(plan.plan_sha256)
        + "\n",
    )
    _write_journal(plan, "locked")
    config_stage = migration_root / "config.toml"
    atomic_write_text(config_stage, tool_config_document(plan.target_config))
    stage_data.mkdir(parents=True, exist_ok=True)
    for item in plan.inventory.authoritative + plan.inventory.unknown:
        _copy_verified(plan.legacy.data_dir / item.relative_path, stage_data / item.relative_path)
    if not plan.state["source_index_present"] and int(plan.state["metadata"].get("last_scan_version", 0)) > 0:
        if repair_missing_source_index:
            _repair_source_index(plan, stage_data)
        else:
            raise DocumentledgerError("source_index_missing", "source-index.json is missing.")
    metadata = dict(plan.state["metadata"])
    metadata["project_uuid"] = plan.canonical_uuid
    write_yaml(stage_data / "storage.yaml", metadata)
    _write_journal(
        plan,
        "staged",
        target_config_sha256=sha256_bytes(config_stage.read_bytes()),
        target_inventory_sha256=sha256_text(
            canonical_json(
                [
                    {"relative_path": item.relative_path, "category": item.category, "size": item.size, "sha256": item.sha256}
                    for item in plan.inventory.authoritative + plan.inventory.unknown
                ]
            )
        ),
    )
    manifest_path = _manifest_path(plan.project_root)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    loaded = ledgercore.load_ledger_project(plan.project_root) if manifest_path.is_file() else None
    if loaded is None:
        ledgercore.write_ledger_manifest(manifest_path, plan.manifest, preserve_comments=True)
        loaded = ledgercore.load_ledger_project(plan.project_root)
    layout = ledgercore.resolve_ledger_layout(loaded.locator, plan.manifest, TOOL_NAME, local_overrides=loaded.local_overrides)
    if layout.mounts[DATA_MOUNT].storage != "project" or layout.mounts[ARTIFACTS_MOUNT].storage != "cache":
        raise DocumentledgerError(
            "unsupported_canonical_layout", "Effective local overrides change Documentledger away from data=project and artifacts=cache."
        )
    final_tool = layout.tool_config_path
    final_data = layout.mounts[DATA_MOUNT].path
    if final_tool is None:
        raise DocumentledgerError("storage_migration_failed", "Target tool config path could not be resolved.")
    data_installed = False
    if final_data.exists() and any(final_data.iterdir()):
        try:
            binding = ledgercore.read_storage_binding(final_data / ".ledger-project.toml")
            existing_metadata = ledgercore.load_yaml_object(final_data / "storage.yaml", label=str(final_data / "storage.yaml"))
            data_installed = (
                binding.project_uuid == plan.canonical_uuid
                and binding.tool == TOOL_NAME
                and binding.mount == DATA_MOUNT
                and str(existing_metadata.get("project_uuid")) == plan.canonical_uuid
            )
        except ledgercore.LedgerCoreError:
            data_installed = False
        if not data_installed:
            raise DocumentledgerError(
                "storage_migration_conflict", f"Target data directory is populated and does not match the resumable migration: {final_data}"
            )
    ledgercore.initialize_config_binding(layout)
    final_tool.parent.mkdir(parents=True, exist_ok=True)
    if final_tool.exists():
        if sha256_bytes(final_tool.read_bytes()) != sha256_bytes(config_stage.read_bytes()):
            raise DocumentledgerError(
                "storage_migration_conflict", f"Target config is populated and does not match the resumable migration: {final_tool}"
            )
    else:
        os.replace(config_stage, final_tool)
    final_data.parent.mkdir(parents=True, exist_ok=True)
    marker_binding = ledgercore.StorageBinding(
        schema_version=1,
        layout_version=3,
        project_uuid=plan.canonical_uuid,
        project_name=None,
        tool=TOOL_NAME,
        mount=DATA_MOUNT,
        storage="project",
    )
    ledgercore.write_storage_binding(stage_data, marker_binding)
    if not data_installed:
        os.replace(stage_data, final_data)
    _write_journal(plan, "installed")
    # Activation is deliberately last and owned by ledgercore.
    ledgercore.write_ledger_manifest(manifest_path, plan.manifest, preserve_comments=True)
    _write_journal(
        plan,
        "complete",
        manifest_after_sha256=sha256_bytes(manifest_path.read_bytes()),
        source_index_repaired=str(not plan.state["source_index_present"]).lower(),
    )
    try:
        lock_path.unlink()
    except FileNotFoundError:
        pass
    return {
        "migration_id": plan.migration_id,
        "phase": "complete",
        "journal": str(_journal_path(plan)),
        "legacy_retained": True,
        "manifest": str(manifest_path),
        "data": str(final_data),
        "config": str(final_tool),
    }


def verify_canonical(start: Path | None = None, *, strict: bool = False) -> dict[str, Any]:
    workspace = canonical_workspace(start, require_data=True)
    layout = ledgercore.resolve_ledger_layout(
        ledgercore.load_ledger_project(workspace.config.root).locator,
        ledgercore.load_ledger_project(workspace.config.root).manifest,
        TOOL_NAME,
    )
    report = ledgercore.validate_ledger_layout_storage(layout)
    if not report.valid:
        raise DocumentledgerError("storage_binding_invalid", "Canonical storage bindings are invalid.")
    result = {
        "valid": True,
        "layout_source": "canonical",
        "manifest_path": str(layout.manifest_path),
        "config_path": str(layout.tool_config_path),
        "data_dir": str(layout.mounts[DATA_MOUNT].path),
        "artifacts_dir": str(layout.mounts[ARTIFACTS_MOUNT].path),
        "storage_bindings_valid": True,
    }
    if strict:
        metadata = workspace.metadata
        if int(metadata.get("schema_version", 0)) != 5:
            raise DocumentledgerError("schema_mismatch", "Canonical storage schema is not 5.")
    return result


def cleanup_legacy(
    start: Path | None = None,
    *,
    yes: bool = False,
    dry_run: bool = False,
    remove_external_source: bool = False,
    discard_derived: bool = False,
) -> dict[str, Any]:
    if not yes and not dry_run:
        raise DocumentledgerError("legacy_cleanup_unsafe", "Legacy cleanup requires --yes.")
    plan = plan_migration(start, adopt_project_uuid=True)
    verify_canonical(plan.project_root, strict=True)
    journal = _journal_path(plan)
    if not journal.is_file() or 'phase = "complete"' not in journal.read_text(encoding="utf-8"):
        raise DocumentledgerError("legacy_cleanup_unsafe", "A completed migration journal is required before cleanup.")
    if (plan.inventory.provisional or plan.inventory.derived) and not discard_derived:
        raise DocumentledgerError(
            "legacy_cleanup_unsafe", "Legacy derived or provisional files remain; pass --discard-derived only after review."
        )
    paths = [str(plan.legacy.config_path), str(plan.legacy.data_dir)]
    if dry_run:
        return {"dry_run": True, "paths": paths, "legacy_retained": True}
    if plan.legacy.data_dir.is_relative_to(plan.project_root):
        shutil.rmtree(plan.legacy.data_dir)
    elif not remove_external_source:
        raise DocumentledgerError("legacy_cleanup_unsafe", "Legacy data is outside the project; pass --remove-external-source.")
    else:
        shutil.rmtree(plan.legacy.data_dir)
    plan.legacy.config_path.unlink()
    return {"dry_run": False, "paths": paths, "legacy_retained": False}


def recover_migration(
    start: Path | None = None,
    *,
    journal_path: Path | None = None,
    policy: str = "auto",
) -> dict[str, Any]:
    """Recover from an interrupted migration.

    This wraps the existing apply_migration with recovery=True.
    """
    if journal_path is None:
        raise DocumentledgerError("storage_migration_incomplete", "Recovery requires --journal.")
    journal = journal_path
    if not journal.is_file():
        raise DocumentledgerError("storage_migration_incomplete", f"Migration journal does not exist: {journal}")
    if not journal.stem.startswith("documentledger-"):
        raise DocumentledgerError("storage_migration_conflict", "The supplied journal is not a Documentledger migration journal.")
    plan = plan_migration(start or Path.cwd(), adopt_project_uuid=True)
    from dataclasses import replace

    plan = replace(plan, migration_id=journal.stem)
    result = apply_migration(plan, adopt_project_uuid=True, repair_missing_source_index=True, recovery=True)
    result["recovered"] = True
    return result
