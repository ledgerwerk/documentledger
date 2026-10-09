"""Canonical ledgercore 0.5 project discovery and layout resolution."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from uuid import uuid4

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10
    import tomli as tomllib

import ledgercore
from ledgercore.errors import LedgerCoreError

from documentledger.config import load_tool_config_v2, write_tool_config_v2
from documentledger.errors import DocumentledgerError
from documentledger.models import Config, ToolConfig, Workspace, WorkspacePaths
from documentledger.storage import read_yaml, validate_storage_metadata

TOOL_NAME = "documentledger"
DATA_MOUNT = "data"
ARTIFACTS_MOUNT = "artifacts"


_SOURCE_DISCOVERY_EXCLUDED = {
    ".git",
    ".ledger",
    ".venv",
    "venv",
    "env",
    "build",
    "dist",
    "docs",
    "scripts",
    "tests",
    "__pycache__",
}


@dataclass(frozen=True, slots=True)
class SourceRootDiscovery:
    roots: tuple[str, ...]
    production_roots: tuple[str, ...]
    test_roots: tuple[str, ...]
    source_file_counts: dict[str, int]
    confidence: str
    reason: str
    project_package: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "source_roots": list(self.roots),
            "production_roots": list(self.production_roots),
            "test_roots": list(self.test_roots),
            "source_file_counts": dict(self.source_file_counts),
            "confidence": self.confidence,
            "reason": self.reason,
            "project_package": self.project_package,
        }


def _python_file_count(path: Path) -> int:
    if path.is_file():
        return int(path.suffix == ".py")
    if not path.is_dir():
        return 0
    return sum(1 for source in path.rglob("*.py") if not any(part in _SOURCE_DISCOVERY_EXCLUDED for part in source.relative_to(path).parts))


def _relative_source_root(root: Path, value: str) -> str:
    normalized = value.replace("\\", "/")
    relative = PurePosixPath(normalized)
    candidate = (root / Path(*relative.parts)).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise DocumentledgerError(
            "source_root_invalid",
            f"Source root must remain inside the project: {value}",
            ["Use a project-relative --source-root path."],
        ) from exc
    if relative.is_absolute() or ".." in relative.parts:
        raise DocumentledgerError(
            "source_root_invalid",
            f"Source root must remain inside the project: {value}",
            ["Use a project-relative --source-root path."],
        )
    normalized_path = relative.as_posix()
    if normalized_path in {"", "."}:
        normalized_path = "."
    if _python_file_count(candidate) == 0:
        raise DocumentledgerError(
            "source_root_empty",
            f"Source root does not exist or contains no Python files: {value}",
            ["Choose an existing source root containing at least one .py file."],
            details={"source_root": normalized_path, "python_file_count": 0},
        )
    return normalized_path


def _metadata_package_roots(root: Path, project_name: str | None) -> tuple[set[str], str | None]:
    pyproject_path = root / "pyproject.toml"
    try:
        pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8")) if pyproject_path.is_file() else {}
    except (OSError, ValueError) as exc:
        raise DocumentledgerError("invalid_pyproject", f"Cannot read project metadata in {pyproject_path}: {exc}") from exc

    project_table = pyproject.get("project", {})
    package_name = str(project_table.get("name") or project_name or root.name)
    import_name = re.sub(r"[-_.]+", "_", package_name)
    roots: set[str] = set()
    for base in (".", "src"):
        candidate = (Path(base) / import_name).as_posix()
        if _python_file_count(root / candidate):
            roots.add(candidate)

    tool_table = pyproject.get("tool", {})
    setuptools = tool_table.get("setuptools", {})
    package_find = setuptools.get("packages", {}).get("find", {})
    where_values = package_find.get("where", ["."])
    includes = package_find.get("include", [])
    for where in where_values:
        for pattern in includes:
            prefix = str(pattern).split("*")[0].rstrip(".")
            if not prefix:
                continue
            candidate = (Path(str(where)) / Path(*prefix.split("."))).as_posix()
            if _python_file_count(root / candidate):
                roots.add(candidate)

    poetry_packages = tool_table.get("poetry", {}).get("packages", [])
    for package in poetry_packages:
        include = str(package.get("include") or "")
        if not include:
            continue
        base = str(package.get("from") or ".")
        candidate = (Path(base) / include).as_posix()
        if _python_file_count(root / candidate):
            roots.add(candidate)
    return roots, package_name


def _conventional_package_roots(root: Path) -> set[str]:
    roots: set[str] = set()
    for parent in (root, root / "src"):
        if not parent.is_dir():
            continue
        for candidate in sorted(parent.iterdir()):
            if (
                candidate.is_dir()
                and candidate.name not in _SOURCE_DISCOVERY_EXCLUDED
                and (candidate / "__init__.py").is_file()
                and _python_file_count(candidate) > 0
            ):
                roots.add(candidate.relative_to(root).as_posix())
    return roots


def discover_source_roots(
    root: Path,
    *,
    project_name: str | None = None,
    source_roots: tuple[str, ...] | list[str] | None = None,
) -> SourceRootDiscovery:
    """Read-only discovery of production and optional test source roots."""
    root = root.resolve()
    test_count = _python_file_count(root / "tests")
    test_roots = ("tests",) if test_count else ()
    package_roots, package_name = _metadata_package_roots(root, project_name)

    if source_roots is not None:
        selected = tuple(dict.fromkeys(_relative_source_root(root, value) for value in source_roots))
        production = tuple(path for path in selected if Path(path).name.casefold() not in {"test", "tests"})
        tests = tuple(path for path in selected if Path(path).name.casefold() in {"test", "tests"})
        counts = {path: _python_file_count(root / path) for path in selected}
        return SourceRootDiscovery(
            roots=selected,
            production_roots=production,
            test_roots=tests,
            source_file_counts=counts,
            confidence="explicit",
            reason="Source roots were explicitly selected by the caller.",
            project_package=package_name,
        )

    if len(package_roots) > 1:
        raise DocumentledgerError(
            "source_root_ambiguous",
            f"Project metadata resolves to multiple Python package roots: {', '.join(sorted(package_roots))}.",
            ["Select the intended roots explicitly with repeatable `documentledger init --source-root PATH` options."],
            details={"candidates": sorted(package_roots)},
        )
    if package_roots:
        production_roots = tuple(sorted(package_roots))
        confidence = "high"
        reason = f"Matched package metadata for {package_name!r} to an existing Python package root."
    else:
        conventional = _conventional_package_roots(root)
        if len(conventional) > 1:
            raise DocumentledgerError(
                "source_root_ambiguous",
                f"Multiple conventional Python package roots were found: {', '.join(sorted(conventional))}.",
                ["Select the intended roots explicitly with repeatable `documentledger init --source-root PATH` options."],
                details={"candidates": sorted(conventional)},
            )
        if conventional:
            production_roots = tuple(sorted(conventional))
            confidence = "medium"
            reason = "Found one conventional Python package directory."
        else:
            module_files = sorted(
                source.name
                for source in root.glob("*.py")
                if source.name not in {"setup.py", "conftest.py", "sitecustomize.py", "__init__.py"}
            )
            if len(module_files) > 1:
                raise DocumentledgerError(
                    "source_root_ambiguous",
                    f"Multiple top-level Python modules were found: {', '.join(module_files)}.",
                    ["Select the intended roots explicitly with repeatable `documentledger init --source-root PATH` options."],
                    details={"candidates": module_files},
                )
            production_roots = tuple(module_files)
            confidence = "medium" if module_files else "none"
            reason = "Found one top-level Python module." if module_files else "No production Python package or module was discovered."

    roots = production_roots + test_roots
    counts = {path: _python_file_count(root / path) for path in roots}
    return SourceRootDiscovery(
        roots=roots,
        production_roots=production_roots,
        test_roots=test_roots,
        source_file_counts=counts,
        confidence=confidence,
        reason=reason,
        project_package=package_name,
    )


def default_tool_config(source_roots: tuple[str, ...] = ()) -> ToolConfig:
    return ToolConfig(
        config_version=2,
        ledger_code="dl",
        source_roots=source_roots,
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
        raise DocumentledgerError("unsupported_documentledger_layout", 'The data mount must use storage = "project".')
    if mounts[ARTIFACTS_MOUNT].storage != "cache":
        raise DocumentledgerError("unsupported_documentledger_layout", 'The artifacts mount must use storage = "cache".')

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


def init_canonical_project(
    root: Path | None = None,
    project_name: str | None = None,
    source_roots: tuple[str, ...] | list[str] | None = None,
) -> Workspace:
    """Create a fresh canonical project and its empty schema-3 stores."""
    root = (root or Path.cwd()).resolve()
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
    discovery = discover_source_roots(
        root,
        project_name=manifest.project_name or project_name,
        source_roots=source_roots,
    )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    ledgercore.write_ledger_manifest(manifest_path, manifest, preserve_comments=True)
    loaded = ledgercore.load_ledger_project(root)
    layout = ledgercore.resolve_ledger_layout(loaded.locator, loaded.manifest, TOOL_NAME, local_overrides=loaded.local_overrides)
    ledgercore.initialize_config_binding(layout)
    ledgercore.initialize_storage_binding(layout.mounts[DATA_MOUNT], require_empty=True)
    assert layout.tool_config_path is not None
    write_tool_config_v2(layout.tool_config_path, default_tool_config(discovery.roots))
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
    workspace = canonical_workspace(root, require_data=True)
    workspace.source_root_discovery = discovery.to_dict()
    return workspace
