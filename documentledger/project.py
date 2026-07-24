"""Canonical ledgercore 0.5 project discovery and layout resolution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import ledgercore
from ledgercore.errors import LedgerCoreError

from documentledger.config import load_tool_config_v2, write_tool_config_v2
from documentledger.errors import DocumentledgerError
from documentledger.models import Config, ToolConfig, Workspace, WorkspacePaths
from documentledger.storage import read_yaml, validate_storage_metadata

TOOL_NAME = "documentledger"
DATA_MOUNT = "data"
ARTIFACTS_MOUNT = "artifacts"


def default_tool_config() -> ToolConfig:
    return ToolConfig(
        config_version=2,
        ledger_code="dl",
        source_roots=("documentledger", "tests"),
        doc_roots=("docs", "README.md"),
        source_extensions=(".py",),
        doc_extensions=(".md", ".rst"),
        validation_commands=(),
        require_doc_frontmatter=False,
    )


@dataclass(frozen=True, slots=True)
class CanonicalProject:
    """A read-only ledgercore project/layout pair."""

    loaded: object
    layout: object
    config: ToolConfig
    paths: WorkspacePaths
    project_name: str
    project_uuid: str


def _raise_core(code: str, message: str, exc: Exception) -> DocumentledgerError:
    return DocumentledgerError(code, message, ["Repair the canonical ledger layout or run the explicit migration."])


def resolve_canonical_project(start: Path | None = None, *, require_data: bool = False) -> CanonicalProject:
    root = (start or Path.cwd()).resolve()
    try:
        loaded = ledgercore.load_ledger_project(
            root,
            legacy_tool_filenames=("documentledger.toml", ".documentledger.toml"),
        )
        manifest = loaded.manifest
        registration = manifest.ledgers.get(TOOL_NAME)
        if registration is None:
            raise DocumentledgerError(
                "documentledger_not_registered",
                "The shared schema-3 manifest does not register documentledger.",
                ["Run `docledger storage migrate --dry-run` and apply the reviewed plan."],
            )
        layout = ledgercore.resolve_ledger_layout(
            loaded.locator,
            manifest,
            TOOL_NAME,
            local_overrides=loaded.local_overrides,
        )
    except DocumentledgerError:
        raise
    except LedgerCoreError as exc:
        raise _raise_core("invalid_canonical_layout", str(exc), exc) from exc

    mounts = dict(layout.mounts)
    if set(mounts) != {DATA_MOUNT, ARTIFACTS_MOUNT}:
        raise DocumentledgerError(
            "unsupported_documentledger_mounts",
            f"documentledger must expose exactly data and artifacts mounts; found {sorted(mounts)}.",
            ["Remove extra mounts and ensure data=project and artifacts=cache."],
        )
    if mounts[DATA_MOUNT].storage != "project":
        raise DocumentledgerError("unsupported_documentledger_layout", "The data mount must use storage = \"project\".")
    if mounts[ARTIFACTS_MOUNT].storage != "cache":
        raise DocumentledgerError("unsupported_documentledger_layout", "The artifacts mount must use storage = \"cache\".")

    report = ledgercore.validate_ledger_layout_storage(layout)
    if not report.valid:
        reasons = [result.reason for result in report.results if not result.valid and result.reason]
        raise DocumentledgerError(
            "invalid_storage_binding",
            "Canonical storage bindings are invalid: " + "; ".join(reasons),
            ["Initialize or repair bindings explicitly; read-only commands never repair them."],
        )
    if layout.tool_config_path is None:
        raise DocumentledgerError("tool_config_missing", "ledgercore did not derive a tool config path.")
    config = load_tool_config_v2(layout.tool_config_path)
    data_path = mounts[DATA_MOUNT].path
    metadata_path = data_path / "storage.yaml"
    metadata: dict[str, object] = {}
    if metadata_path.exists():
        metadata = validate_storage_metadata(read_yaml(metadata_path))
        if str(metadata.get("project_uuid")) != manifest.project_uuid:
            raise DocumentledgerError(
                "project_uuid_mismatch",
                "storage.yaml project_uuid does not match the shared manifest UUID.",
                ["Review the migration identity decision before activation."],
            )
    elif require_data:
        raise DocumentledgerError("storage_missing", f"Canonical storage metadata is missing: {metadata_path}.")

    paths = WorkspacePaths(
        project_root=layout.project_root,
        manifest_path=layout.manifest_path,
        local_config_path=layout.local_config_path,
        config_path=layout.tool_config_path,
        data_dir=data_path,
        artifacts_dir=mounts[ARTIFACTS_MOUNT].path,
        config_binding_path=layout.config_binding_path,
        data_binding_path=mounts[DATA_MOUNT].binding_path,
        artifacts_binding_path=mounts[ARTIFACTS_MOUNT].binding_path,
        layout_source="canonical",
    )
    return CanonicalProject(
        loaded=loaded,
        layout=layout,
        config=config,
        paths=paths,
        project_name=manifest.project_name or layout.project_root.name,
        project_uuid=manifest.project_uuid,
    )


def canonical_workspace(start: Path | None = None, *, require_data: bool = False) -> Workspace:
    project = resolve_canonical_project(start, require_data=require_data)
    metadata_path = project.paths.data_dir / "storage.yaml"
    metadata = validate_storage_metadata(read_yaml(metadata_path)) if metadata_path.exists() else {}
    compatibility_config = Config(
        root=project.paths.project_root,
        path=project.paths.config_path,
        project_name=project.project_name,
        project_uuid=project.project_uuid,
        storage_dir=project.paths.data_dir,
        source_roots=list(project.config.source_roots),
        doc_roots=list(project.config.doc_roots),
        source_extensions=list(project.config.source_extensions),
        doc_extensions=list(project.config.doc_extensions),
        validation_commands=list(project.config.validation_commands),
        require_doc_frontmatter=project.config.require_doc_frontmatter,
    )
    return Workspace(
        config=compatibility_config,
        paths=project.paths,
        project_name=project.project_name,
        project_uuid=project.project_uuid,
        metadata=metadata,
    )


def initialize_canonical_bindings(layout: object) -> None:
    """Initialize config/data/artifact markers; callers must opt into writes."""
    ledgercore.initialize_config_binding(layout)
    ledgercore.initialize_storage_binding(layout.mounts[DATA_MOUNT], require_empty=True)  # type: ignore[attr-defined]
    ledgercore.initialize_storage_binding(layout.mounts[ARTIFACTS_MOUNT], require_empty=True)  # type: ignore[attr-defined]


def init_canonical_project(project_name: str | None = None) -> Workspace:
    """Create a fresh canonical project and its empty schema-3 stores."""
    root = Path.cwd().resolve()
    manifest_path = root / ".ledger" / "ledger.toml"
    if manifest_path.exists():
        try:
            loaded = ledgercore.load_ledger_project(root)
        except LedgerCoreError as exc:
            raise _raise_core("invalid_canonical_layout", str(exc), exc) from exc
        if TOOL_NAME in loaded.manifest.ledgers:
            raise DocumentledgerError("already_initialized", "Documentledger is already registered in the canonical ledger project.")
        manifest = loaded.manifest
        from dataclasses import replace
        from ledgercore.manifest import LedgerRegistration, MountDefinition

        ledgers = dict(manifest.ledgers)
        ledgers[TOOL_NAME] = LedgerRegistration(
            name=TOOL_NAME,
            mounts={
                DATA_MOUNT: MountDefinition(name=DATA_MOUNT, storage="project"),
                ARTIFACTS_MOUNT: MountDefinition(name=ARTIFACTS_MOUNT, storage="cache"),
            },
        )
        manifest = replace(manifest, ledgers=ledgers)
    else:
        from ledgercore.manifest import LedgerProjectManifest, LedgerRegistration, MountDefinition

        manifest = LedgerProjectManifest(
            schema_version=3,
            project_uuid=str(uuid4()),
            project_name=project_name or root.name,
            ledgers={
                TOOL_NAME: LedgerRegistration(
                    name=TOOL_NAME,
                    mounts={
                        DATA_MOUNT: MountDefinition(name=DATA_MOUNT, storage="project"),
                        ARTIFACTS_MOUNT: MountDefinition(name=ARTIFACTS_MOUNT, storage="cache"),
                    },
                )
            },
        )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    ledgercore.write_ledger_manifest(manifest_path, manifest, preserve_comments=True)
    loaded = ledgercore.load_ledger_project(root)
    layout = ledgercore.resolve_ledger_layout(loaded.locator, loaded.manifest, TOOL_NAME, local_overrides=loaded.local_overrides)
    ledgercore.initialize_config_binding(layout)
    ledgercore.initialize_storage_binding(layout.mounts[DATA_MOUNT], require_empty=True)
    assert layout.tool_config_path is not None
    write_tool_config_v2(layout.tool_config_path, default_tool_config())
    data_dir = layout.mounts[DATA_MOUNT].path
    metadata = {
        "schema_version": 5,
        "project_uuid": loaded.manifest.project_uuid,
        "state_version": 1,
        "last_scan_version": 0,
        "last_scan_source_file_count": 0,
        "last_scan_source_unit_count": 0,
        "last_scan_doc_file_count": 0,
        "last_scan_changed_source_count": 0,
        "last_scan_affected_section_count": 0,
        "last_scan_stale_doc_count": 0,
        "last_scan_unlinked_changed_source_count": 0,
        "last_scan_source_index_file": "source-index.json",
        "last_scan_source_index_hash": "",
    }
    from documentledger.storage import write_yaml

    write_yaml(data_dir / "storage.yaml", metadata)
    return canonical_workspace(root, require_data=True)
