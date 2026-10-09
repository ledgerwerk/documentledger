"""Root-level commands: init, status, info, doctor, check, next-action, scan, coverage, commands, help."""

from __future__ import annotations

from pathlib import Path
from time import perf_counter
from typing import Annotated, Any

import typer

from documentledger.cli_support import emit_success, get_state, handle_command_error
from documentledger.errors import DocumentledgerError
from documentledger.storage import (
    STORAGE_SCHEMA_VERSION,
    coerce_int,
    iter_doc_records,
    latest_scan,
    load_workspace,
)

# Import domain functions lazily where needed to avoid circular imports.


def _profile_events(ctx: typer.Context, operation: str, started_at: float) -> list[dict[str, Any]]:
    state = get_state(ctx)
    if not state.json_output:
        return []
    return [{"event": "profile", "operation": operation, "elapsed_ms": round((perf_counter() - started_at) * 1000, 3)}]


def _scan_diagnostics(workspace: Any) -> list[dict[str, Any]]:
    from documentledger.scanner import collect_files

    issues: list[dict[str, Any]] = []
    source_roots = list(workspace.config.source_roots)
    source_counts: dict[str, int] = {}
    tests_count = 0
    production_count = 0
    for root_text in source_roots:
        path = workspace.config.root / root_text
        if not path.exists():
            issues.append({"code": "missing_source_root", "message": f"Configured source root does not exist: {root_text}"})
            continue
        files = collect_files(workspace, [root_text], workspace.config.source_extensions)
        source_counts[root_text] = len(files)
        if not files:
            issues.append({"code": "empty_source_root", "message": f"No source files were collected from configured root: {root_text}"})
        if root_text.startswith("test"):
            tests_count += len(files)
        else:
            production_count += len(files)
    try:
        from documentledger.project import discover_source_roots

        discovery = discover_source_roots(workspace.config.root, project_name=workspace.config.project_name)
    except DocumentledgerError as exc:
        if exc.code == "source_root_ambiguous" and production_count > 0:
            discovery = None
        else:
            issues.append({"code": exc.code, "message": exc.message, "remediation": exc.remediation})
            discovery = None
    if discovery is not None and discovery.production_roots:
        configured_production_roots = [root_text for root_text in source_roots if not Path(root_text).name.casefold().startswith("test")]
        missing_roots = [
            expected
            for expected in discovery.production_roots
            if not any(
                configured == "." or expected == configured or expected.startswith(configured.rstrip("/") + "/")
                for configured in configured_production_roots
            )
        ]
        if missing_roots:
            expected_roots = list(discovery.production_roots) + list(discovery.test_roots)
            roots_literal = ", ".join(f'"{root}"' for root in expected_roots)
            issues.append(
                {
                    "code": "package_root_not_configured",
                    "message": f"Configured source roots omit the detected production package root(s): {', '.join(missing_roots)}.",
                    "remediation": f"Set [scan].source_roots to [{roots_literal}] after reviewing the detected Python roots.",
                }
            )
    if production_count == 0 and tests_count > 0:
        issues.append(
            {
                "code": "tests_without_production_root",
                "message": "Most indexed sources would come from tests while the production package is absent.",
            }
        )
    return issues


def _status_classification(workspace: Any) -> tuple[str, str, str]:
    from documentledger.storage import iter_doc_records

    last_scan_version = coerce_int(workspace.metadata.get("last_scan_version"), 0)
    affected_count = coerce_int(workspace.metadata.get("last_scan_affected_section_count"), 0)
    unlinked_changed = coerce_int(workspace.metadata.get("last_scan_unlinked_changed_source_count"), 0)
    linked_sections = sum(
        1 for record in iter_doc_records(workspace) for section in (record.get("sections", []) or []) if section.get("links")
    )
    if last_scan_version <= 0:
        return ("bootstrap_required", "No baseline scan exists yet.", "documentledger scan")
    if linked_sections <= 0:
        return (
            "bootstrap_required",
            "A baseline scan exists but no documentation links exist.",
            "documentledger document build-context --bootstrap",
        )
    if affected_count > 0:
        return (
            "incremental_affected",
            "Linked documentation sections are affected by the latest source changes.",
            "documentledger document build-context --affected",
        )
    if unlinked_changed > 0:
        return (
            "mapping_incomplete",
            "Changed source files are not fully linked to documentation.",
            "documentledger link propose --all-docs",
        )
    return ("incremental_clean", "No affected linked sections remain after the latest scan.", "documentledger scan")


def _display_path(root: Path, path: Path) -> str:
    from os.path import relpath

    root_resolved = root.resolve()
    path_resolved = path.resolve()
    try:
        return path_resolved.relative_to(root_resolved).as_posix()
    except ValueError:
        return Path(relpath(path_resolved, root_resolved)).as_posix()


def _doctor_issues(workspace: Any) -> list[dict[str, Any]]:
    from documentledger.identity import normalize_repo_path
    from documentledger.links import audit_links

    issues: list[dict[str, Any]] = list(_scan_diagnostics(workspace))
    if workspace.metadata.get("schema_version") != STORAGE_SCHEMA_VERSION:
        issues.append({"code": "schema_mismatch", "message": f"storage.yaml schema_version is not {STORAGE_SCHEMA_VERSION}"})
    for record in iter_doc_records(workspace):
        doc_path = str(record.get("doc_path", ""))
        try:
            normalize_repo_path(doc_path)
        except DocumentledgerError as exc:
            issues.append({"code": exc.code, "message": exc.message})
        if not (workspace.config.root / doc_path).exists():
            issues.append({"code": "missing_doc", "message": f"Missing doc file: {doc_path}"})
    if coerce_int(workspace.metadata.get("last_scan_version"), 0) > 0 and latest_scan(workspace) is None:
        issues.append({"code": "scan_missing", "message": "storage metadata references a latest scan, but scan.yaml is missing."})
    issues.extend(list(audit_links(workspace).get("issues", [])))
    return issues


def _readiness_fields(
    workspace: Any,
    health_issues: list[dict[str, Any]],
    *,
    required_pages: list[str] | None = None,
    navigation_targets: list[str] | None = None,
) -> dict[str, Any]:
    from documentledger.verification import completion_status

    return completion_status(
        workspace,
        required_pages=required_pages,
        navigation_targets=navigation_targets,
        health_issues=health_issues,
    )


def _status_result(workspace: Any | None) -> dict[str, Any]:
    if workspace is None:
        return {
            "initialized": False,
            "state": "uninitialized",
            "storage_present": False,
            "config_path": None,
            "storage_dir": None,
            "project_name": None,
            "project_uuid": None,
            "last_scan_version": None,
            "recommended_command": "documentledger init",
            "recommended_reason": "No Documentledger workspace exists yet.",
            "remediation": ["Run `documentledger init` from the project root."],
            "health": {"state": "uninitialized", "issues": []},
            "mapping": {"state": "not_initialized"},
            "documentation": {"state": "incomplete", "validation_state": "not_run"},
            "completion": {"ready": False, "blocking_reasons": ["workspace_not_initialized"]},
        }
    config_rel = _display_path(workspace.config.root, workspace.config.path)
    storage_rel = _display_path(workspace.config.root, workspace.config.storage_dir)
    storage_present = (workspace.config.storage_dir / "storage.yaml").exists()
    paths = getattr(workspace, "paths", None)
    layout_source = "canonical" if paths is not None and paths.layout_source == "canonical" else "legacy"
    if not storage_present:
        return {
            "initialized": False,
            "state": "uninitialized",
            "storage_present": False,
            "config_path": config_rel,
            "storage_dir": storage_rel,
            "data_dir": storage_rel,
            "layout_source": layout_source,
            "project_name": workspace.config.project_name,
            "project_uuid": workspace.config.project_uuid,
            "last_scan_version": None,
            "recommended_command": "documentledger init",
            "recommended_reason": "The config exists but storage metadata is missing.",
            "remediation": ["Run `documentledger init` from the project root to create storage metadata."],
            "health": {"state": "uninitialized", "issues": []},
            "mapping": {"state": "not_initialized"},
            "documentation": {"state": "incomplete", "validation_state": "not_run"},
            "completion": {"ready": False, "blocking_reasons": ["storage_not_initialized"]},
        }
    issues = _scan_diagnostics(workspace)
    state, reason, command = _status_classification(workspace)
    affected_count = coerce_int(workspace.metadata.get("last_scan_affected_section_count"), 0)
    unlinked_changed = coerce_int(workspace.metadata.get("last_scan_unlinked_changed_source_count"), 0)
    linked_sections = sum(
        1 for record in iter_doc_records(workspace) for section in (record.get("sections", []) or []) if section.get("links")
    )
    freshness_state = "clean" if affected_count == 0 else "affected"
    coverage_review_required = linked_sections <= 0 or unlinked_changed > 0
    result = {
        "initialized": True,
        "state": state,
        "storage_present": True,
        "config_path": config_rel,
        "storage_dir": storage_rel,
        "data_dir": storage_rel,
        "layout_source": layout_source,
        "project_name": workspace.config.project_name,
        "project_uuid": workspace.metadata.get("project_uuid") or workspace.config.project_uuid,
        "last_scan_version": coerce_int(workspace.metadata.get("last_scan_version"), 0) or None,
        "last_scan_source_file_count": coerce_int(workspace.metadata.get("last_scan_source_file_count"), 0),
        "last_scan_source_unit_count": coerce_int(workspace.metadata.get("last_scan_source_unit_count"), 0),
        "last_scan_doc_file_count": coerce_int(workspace.metadata.get("last_scan_doc_file_count"), 0),
        "last_scan_affected_section_count": coerce_int(workspace.metadata.get("last_scan_affected_section_count"), 0),
        "last_scan_unlinked_changed_source_count": coerce_int(workspace.metadata.get("last_scan_unlinked_changed_source_count"), 0),
        "recommended_command": command,
        "recommended_reason": reason,
        "freshness_state": freshness_state,
        "mapping_state": "review_required" if coverage_review_required else "not_stale",
        "coverage_review_required": coverage_review_required,
        "coverage": {
            "documents_with_records": len(iter_doc_records(workspace)),
            "sections_linked": linked_sections,
        },
        "issues": issues,
    }
    result.update(_readiness_fields(workspace, _doctor_issues(workspace)))
    if paths is not None:
        result.update(
            {
                "manifest_path": _display_path(paths.project_root, paths.manifest_path) if paths.manifest_path else None,
                "artifacts_dir": str(paths.artifacts_dir) if paths.artifacts_dir else None,
                "storage_bindings_valid": True,
                "legacy_cleanup_available": False,
            }
        )
    return result


def register_root_commands(app: typer.Typer) -> None:  # noqa: C901
    """Register root-level commands on the main app."""

    @app.command()
    @handle_command_error("init")
    def init(
        ctx: typer.Context,
        project_name: str | None = typer.Option(None, "--project-name"),
        source_roots: Annotated[
            list[str] | None,
            typer.Option("--source-root", help="Explicit source root; repeat for multiple roots."),
        ] = None,
        documentledger_dir: str = typer.Option(".ledger", "--documentledger-dir"),
        hidden_config: bool = typer.Option(False, "--hidden-config"),
    ) -> None:
        if documentledger_dir != ".ledger" or hidden_config:
            raise DocumentledgerError(
                "legacy_init_options_unsupported",
                "Fresh initialization uses the canonical schema-3 .ledger layout; legacy storage options are migration-only.",
                ["Run `documentledger init --project-name NAME` or migrate the existing workspace explicitly."],
            )
        state = get_state(ctx)
        from documentledger.project import init_canonical_project

        workspace = init_canonical_project(state.root, project_name, source_roots=source_roots)
        result = _status_result(workspace)
        if workspace.source_root_discovery is not None:
            result["source_root_discovery"] = workspace.source_root_discovery
        emit_success(ctx, "init", result, f"Initialized Documentledger for {workspace.config.project_name}")

    @app.command()
    @handle_command_error("status")
    def status(ctx: typer.Context) -> None:
        started_at = perf_counter()
        state = get_state(ctx)
        workspace = load_workspace(start=state.root, required=False)
        result = _status_result(workspace)
        human = "Documentledger initialized." if result["initialized"] else "Documentledger is not initialized."
        emit_success(ctx, "status", result, human, _profile_events(ctx, "status", started_at))

    @app.command()
    @handle_command_error("info")
    def info(ctx: typer.Context) -> None:
        started_at = perf_counter()
        state = get_state(ctx)
        workspace = load_workspace(start=state.root)
        paths = getattr(workspace, "paths", None)
        result: dict[str, Any] = {
            "project_root": str(workspace.config.root),
            "project_name": workspace.config.project_name,
            "project_uuid": workspace.metadata.get("project_uuid") or workspace.config.project_uuid,
        }
        if paths is not None:
            result.update(
                {
                    "manifest_path": str(paths.manifest_path),
                    "config_path": str(paths.config_path),
                    "data_dir": str(paths.data_dir),
                    "artifacts_dir": str(paths.artifacts_dir) if paths.artifacts_dir else None,
                    "layout_source": paths.layout_source,
                }
            )
        result["scan_counters"] = {
            "last_scan_version": coerce_int(workspace.metadata.get("last_scan_version"), 0),
            "source_file_count": coerce_int(workspace.metadata.get("last_scan_source_file_count"), 0),
            "source_unit_count": coerce_int(workspace.metadata.get("last_scan_source_unit_count"), 0),
            "doc_file_count": coerce_int(workspace.metadata.get("last_scan_doc_file_count"), 0),
            "affected_section_count": coerce_int(workspace.metadata.get("last_scan_affected_section_count"), 0),
        }
        doc_records = iter_doc_records(workspace)
        result["document_count"] = len(doc_records)
        result["section_count"] = sum(len(r.get("sections", []) or []) for r in doc_records)
        result["linked_section_count"] = sum(1 for r in doc_records for s in (r.get("sections", []) or []) if s.get("links"))
        emit_success(ctx, "info", result, "Info retrieved.", _profile_events(ctx, "info", started_at))

    @app.command()
    @handle_command_error("doctor")
    def doctor(ctx: typer.Context, strict: bool = typer.Option(False, "--strict")) -> None:
        started_at = perf_counter()
        state = get_state(ctx)
        workspace = load_workspace(start=state.root)
        issues = _doctor_issues(workspace)
        result = {"ok": not issues, "issues": issues}
        if strict and issues:
            raise DocumentledgerError(
                "doctor_failed",
                f"Doctor found {len(issues)} issue(s).",
                ["Resolve the listed health issues and rerun `documentledger doctor --strict`."],
                details={"issues": issues},
            )
        emit_success(
            ctx, "doctor", result, "Doctor passed." if not issues else "Doctor found issues.", _profile_events(ctx, "doctor", started_at)
        )

    @app.command()
    @handle_command_error("check")
    def check(
        ctx: typer.Context,
        complete: bool = typer.Option(False, "--complete"),
        required_pages: Annotated[list[str] | None, typer.Option("--required-page")] = None,
        navigation_targets: Annotated[list[str] | None, typer.Option("--navigation-target")] = None,
    ) -> None:
        """Deterministic CI gate."""
        started_at = perf_counter()
        state = get_state(ctx)
        workspace = load_workspace(start=state.root)
        issues: list[dict[str, str]] = []

        # Check storage schema
        if workspace.metadata.get("schema_version") != STORAGE_SCHEMA_VERSION:
            issues.append({"code": "schema_mismatch", "message": f"storage.yaml schema_version is not {STORAGE_SCHEMA_VERSION}"})

        # Check source index integrity
        from documentledger.storage import load_scan_summary, load_source_index

        summary = load_scan_summary(workspace)
        if summary:
            try:
                load_source_index(workspace, summary)
            except DocumentledgerError as exc:
                issues.append({"code": exc.code, "message": exc.message})

        # Check broken links
        from documentledger.links import audit_links

        audit = audit_links(workspace)
        issues.extend(audit.get("issues", []))

        # Check stale docs
        from documentledger.impact import resolve_affected_sections

        affected = resolve_affected_sections(workspace)
        if affected:
            issues.append(
                {
                    "code": "stale_documentation",
                    "message": f"{len(affected)} documentation sections are stale.",
                }
            )

        readiness: dict[str, Any] | None = None
        if complete:
            readiness = _readiness_fields(
                workspace,
                _doctor_issues(workspace),
                required_pages=required_pages or None,
                navigation_targets=navigation_targets or None,
            )
            if not readiness["completion"]["ready"]:
                issues.append(
                    {
                        "code": "documentation_completion_incomplete",
                        "message": "Documentation completion gate is blocked: " + ", ".join(readiness["completion"]["blocking_reasons"]),
                    }
                )
        result = {"ok": not issues, "issues": issues} | ({"readiness": readiness} if readiness is not None else {})
        human = "Check passed." if not issues else f"Check found {len(issues)} issue(s)."
        if issues:
            raise DocumentledgerError(
                "check_failed",
                human,
                ["Resolve the reported validation issues and rerun `documentledger check`."],
                details={"issues": issues, **({"readiness": readiness} if readiness is not None else {})},
            )
        emit_success(ctx, "check", result, human, _profile_events(ctx, "check", started_at))

    @app.command("next-action")
    @handle_command_error("next-action")
    def next_action(ctx: typer.Context) -> None:
        state = get_state(ctx)
        workspace = load_workspace(start=state.root, required=False)
        if workspace is None:
            result = {
                "command": "documentledger init",
                "reason": "No Documentledger workspace exists yet.",
                "prerequisites": [],
            }
            emit_success(ctx, "next-action", result, "Run `documentledger init`.")
            return
        classification, reason, command = _status_classification(workspace)
        result = {
            "command": command,
            "reason": reason,
            "classification": classification,
            "prerequisites": [],
        }
        emit_success(ctx, "next-action", result, f"Next: {command}\nReason: {reason}")

    @app.command()
    @handle_command_error("scan")
    def scan(ctx: typer.Context) -> None:
        started_at = perf_counter()
        state = get_state(ctx)
        from documentledger.scanner import run_scan

        result_obj = run_scan(load_workspace(start=state.root))
        result = {
            "version": result_obj.version,
            "unchanged": result_obj.unchanged,
            "changed_sources": result_obj.changed_sources,
            "deleted_sources": result_obj.deleted_sources,
            "changed_units": result_obj.changed_units,
            "added_units": result_obj.added_units,
            "deleted_units": result_obj.deleted_units,
            "affected_sections": result_obj.affected_sections,
            "stale_docs": result_obj.stale_docs,
            "unlinked_changed_sources": result_obj.unlinked_changed_sources,
            "unmapped_changed_units": result_obj.unmapped_changed_units,
            "reconciliation": result_obj.reconciliation,
        }
        human = (
            f"No tracked file changes since scan version {result_obj.version}"
            if result_obj.unchanged
            else f"Recorded scan version {result_obj.version}"
        )
        emit_success(ctx, "scan", result, human, _profile_events(ctx, "scan", started_at))

    @app.command("coverage")
    @handle_command_error("coverage")
    def coverage(ctx: typer.Context) -> None:
        started_at = perf_counter()
        state = get_state(ctx)
        workspace = load_workspace(start=state.root)
        from documentledger.verification import coverage_metrics

        result = coverage_metrics(workspace)
        readiness = _readiness_fields(workspace, _doctor_issues(workspace))
        result.update(readiness)
        emit_success(ctx, "coverage", result, "Coverage computed.", _profile_events(ctx, "coverage", started_at))

    @app.command("commands")
    @handle_command_error("commands")
    def commands(ctx: typer.Context) -> None:
        from documentledger.command_catalog import COMMAND_INVENTORY

        # state intentionally unused — commands catalog is stateless
        result = {"commands": [entry.as_mapping() for entry in COMMAND_INVENTORY.entries]}
        human = COMMAND_INVENTORY.human_table()
        emit_success(ctx, "commands", result, human)

    @app.command("help", no_args_is_help=True)
    @handle_command_error("help")
    def help_cmd(
        ctx: typer.Context,
        command_path: Annotated[list[str], typer.Argument(help="Command path to show help for.")] = [],  # noqa: B006
    ) -> None:
        from documentledger.command_catalog import COMMAND_INVENTORY

        # state intentionally unused — help catalog is stateless
        path = " ".join(command_path)
        meta = COMMAND_INVENTORY.resolve(path)
        if meta is None:
            raise DocumentledgerError("command_not_found", f"Unknown command: {path}")
        result = meta.as_mapping()
        human = f"{meta.path}: {meta.summary}"
        if meta.aliases:
            human += f"\nAliases: {', '.join(meta.aliases)}"
        emit_success(ctx, "help", result, human)
