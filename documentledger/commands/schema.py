"""Schema commands: list, show, values."""

from __future__ import annotations

from typing import Any

import typer

from documentledger.cli_support import emit_success, handle_command_error

# Known schema definitions
_SCHEMAS: dict[str, dict[str, Any]] = {
    "storage": {
        "name": "storage",
        "schema_id": "documentledger.storage.v5",
        "description": "Storage metadata schema for Documentledger workspace state.",
        "fields": [
            "schema_version",
            "project_uuid",
            "state_version",
            "last_scan_version",
            "last_scan_source_file_count",
            "last_scan_source_unit_count",
            "last_scan_doc_file_count",
            "last_scan_changed_source_count",
            "last_scan_affected_section_count",
            "last_scan_stale_doc_count",
            "last_scan_unlinked_changed_source_count",
            "last_scan_source_index_file",
            "last_scan_source_index_hash",
        ],
    },
    "scan": {
        "name": "scan",
        "schema_id": "documentledger.scan.v5",
        "description": "Scan result schema for source and documentation changes.",
        "fields": [
            "schema",
            "version",
            "source_index_file",
            "source_index_hash",
            "source_file_count",
            "source_unit_count",
            "doc_file_count",
            "source_hashes",
            "doc_hashes",
            "changed_sources",
            "deleted_sources",
            "changed_units",
            "added_units",
            "deleted_units",
            "affected_sections",
            "stale_docs",
            "unlinked_changed_sources",
            "unmapped_changed_units",
        ],
    },
    "source-index": {
        "name": "source-index",
        "schema_id": "documentledger.source_index.v1",
        "description": "Source index schema for tracked source units.",
        "fields": ["schema", "source_units"],
    },
    "doc-record": {
        "name": "doc-record",
        "schema_id": "documentledger.doc_record.v4",
        "description": "Documentation record schema for tracked documents.",
        "fields": [
            "schema",
            "doc_path",
            "linked_sources",
            "sections",
            "last_fresh_scan_version",
            "last_fresh_hash",
            "notes",
            "version",
        ],
    },
    "mapping-batch": {
        "name": "mapping-batch",
        "schema_id": "documentledger.mapping_batch.v1",
        "description": "Mapping batch schema for bulk link imports.",
        "fields": ["schema", "doc_path", "sections"],
    },
    "migration-plan": {
        "name": "migration-plan",
        "schema_id": "documentledger.migration-plan.v2",
        "description": "Migration plan schema for storage layout migrations.",
        "fields": [
            "schema",
            "migration",
            "migration_id",
            "project_uuid",
            "source",
            "target",
            "items",
            "warnings",
            "plan_sha256",
        ],
    },
}


def register_schema_commands(app: typer.Typer, schema_app: typer.Typer) -> None:
    """Register schema commands on the schema app."""

    @schema_app.command("list")
    @handle_command_error("schema list")
    def schema_list(ctx: typer.Context) -> None:
        """List known schema names."""
        result = {"schemas": list(_SCHEMAS.keys())}
        emit_success(ctx, "schema list", result, "\n".join(_SCHEMAS.keys()))

    @schema_app.command("show")
    @handle_command_error("schema show")
    def schema_show(ctx: typer.Context, name: str = typer.Argument(...)) -> None:
        """Show metadata for a schema."""
        if name not in _SCHEMAS:
            from documentledger.errors import DocumentledgerError

            raise DocumentledgerError("schema_not_found", f"Unknown schema: {name}. Known: {', '.join(_SCHEMAS.keys())}")
        emit_success(ctx, "schema show", _SCHEMAS[name], f"Schema: {name}")

    @schema_app.command("values")
    @handle_command_error("schema values")
    def schema_values(ctx: typer.Context, name: str | None = typer.Argument(None)) -> None:
        """Show known values for a schema."""
        if name is None:
            result = {key: schema["fields"] for key, schema in _SCHEMAS.items()}
            emit_success(ctx, "schema values", result, "All schema fields listed.")
            return
        if name not in _SCHEMAS:
            from documentledger.errors import DocumentledgerError

            raise DocumentledgerError("schema_not_found", f"Unknown schema: {name}. Known: {', '.join(_SCHEMAS.keys())}")
        result = {"name": name, "fields": _SCHEMAS[name]["fields"]}
        emit_success(ctx, "schema values", result, f"Fields for schema: {name}")
