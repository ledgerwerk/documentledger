"""Command metadata catalog for Documentledger.

Defines every canonical command and alias in a CommandInventory.
Used by: commands, help, generated CLI reference, drift tests.
"""
from __future__ import annotations

from ledgercore.cli import CommandInventory, CommandMetadata

# All canonical commands with their metadata.
_COMMANDS: tuple[CommandMetadata, ...] = (
    # Root commands
    CommandMetadata(
        path="init",
        summary="Initialize Documentledger storage for a project.",
        audience="agent",
        effect="workspace-write",
        requires_workspace=False,
    ),
    CommandMetadata(
        path="status",
        summary="Show concise Documentledger status.",
        audience="both",
        effect="read",
        requires_workspace=False,
    ),
    CommandMetadata(
        path="info",
        summary="Show full Documentledger storage and configuration inventory.",
        audience="both",
        effect="read",
    ),
    CommandMetadata(
        path="doctor",
        summary="Run detailed read-only diagnostics.",
        audience="both",
        effect="read",
    ),
    CommandMetadata(
        path="check",
        summary="Run deterministic CI validation gate.",
        audience="agent",
        effect="read",
    ),
    CommandMetadata(
        path="next-action",
        summary="Show the single recommended next command.",
        audience="agent",
        effect="read",
        requires_workspace=False,
    ),
    CommandMetadata(
        path="scan",
        summary="Run an incremental source scan.",
        audience="agent",
        effect="workspace-write",
    ),
    CommandMetadata(
        path="coverage",
        summary="Compute documentation coverage metrics.",
        audience="both",
        effect="read",
    ),
    CommandMetadata(
        path="commands",
        summary="List all registered commands.",
        audience="both",
        effect="read",
        requires_workspace=False,
    ),
    CommandMetadata(
        path="help",
        summary="Show help for a command path.",
        audience="both",
        effect="read",
        requires_workspace=False,
        targeting="command-path",
    ),
    # Config group
    CommandMetadata(
        path="config show",
        summary="Show effective Documentledger configuration.",
        audience="both",
        effect="read",
    ),
    CommandMetadata(
        path="config validate",
        summary="Validate the effective tool config.",
        audience="agent",
        effect="read",
    ),
    # Schema group
    CommandMetadata(
        path="schema list",
        summary="List known schema names.",
        audience="agent",
        effect="read",
        requires_workspace=False,
    ),
    CommandMetadata(
        path="schema show",
        summary="Show metadata for a schema.",
        audience="agent",
        effect="read",
        requires_workspace=False,
        targeting="schema-name",
    ),
    CommandMetadata(
        path="schema values",
        summary="Show known values for a schema.",
        audience="agent",
        effect="read",
        requires_workspace=False,
        targeting="schema-name",
    ),
    # Document group (canonical singular)
    CommandMetadata(
        path="document list",
        summary="List tracked documentation files.",
        audience="both",
        effect="read",
        aliases=("docs list",),
    ),
    CommandMetadata(
        path="document sections",
        summary="Show sections in documentation files.",
        audience="both",
        effect="read",
        targeting="document-or-section",
        aliases=("docs sections",),
    ),
    CommandMetadata(
        path="document affected",
        summary="Show documentation sections affected by source changes.",
        audience="agent",
        effect="read",
        aliases=("docs affected",),
    ),
    CommandMetadata(
        path="document stale",
        summary="Show stale documentation details.",
        audience="agent",
        effect="read",
        aliases=("docs stale",),
    ),
    CommandMetadata(
        path="document build-context",
        summary="Build a bounded documentation update context.",
        audience="agent",
        effect="workspace-write",
        targeting="document-or-section",
        aliases=("docs build-context",),
    ),
    CommandMetadata(
        path="document mark-fresh",
        summary="Mark documentation sections as fresh.",
        audience="agent",
        effect="workspace-write",
        targeting="document-or-section",
        aliases=("mark-fresh",),
    ),
    # Source group (canonical singular)
    CommandMetadata(
        path="source list",
        summary="List source units in the inventory.",
        audience="both",
        effect="read",
        aliases=("sources list",),
    ),
    CommandMetadata(
        path="source show",
        summary="Show details for a source unit.",
        audience="both",
        effect="read",
        targeting="source-unit",
        aliases=("sources show",),
    ),
    # Link group (canonical singular)
    CommandMetadata(
        path="link list",
        summary="List documentation-to-source links.",
        audience="both",
        effect="read",
        aliases=("links list",),
    ),
    CommandMetadata(
        path="link add",
        summary="Add a documentation-to-source link.",
        audience="agent",
        effect="workspace-write",
        aliases=("links add",),
    ),
    CommandMetadata(
        path="link remove",
        summary="Remove a documentation-to-source link.",
        audience="agent",
        effect="workspace-write",
        aliases=("links remove",),
    ),
    CommandMetadata(
        path="link add-section",
        summary="Add a section-level source link.",
        audience="agent",
        effect="workspace-write",
        aliases=("links add-section",),
    ),
    CommandMetadata(
        path="link remove-section",
        summary="Remove a section-level source link.",
        audience="agent",
        effect="workspace-write",
        aliases=("links remove-section",),
    ),
    CommandMetadata(
        path="link import-map",
        summary="Import a mapping batch of links.",
        audience="agent",
        effect="workspace-write",
        aliases=("links import-map",),
    ),
    CommandMetadata(
        path="link audit",
        summary="Audit links for consistency.",
        audience="agent",
        effect="read",
        aliases=("links audit",),
    ),
    CommandMetadata(
        path="link propose",
        summary="Propose new links from source inventory.",
        audience="agent",
        effect="workspace-write",
        aliases=("links propose",),
    ),
    # Storage group
    CommandMetadata(
        path="storage where",
        summary="Show Documentledger storage locations.",
        audience="both",
        effect="read",
        requires_workspace=False,
    ),
    CommandMetadata(
        path="storage validate",
        summary="Validate canonical storage bindings.",
        audience="agent",
        effect="read",
        aliases=("storage verify",),
    ),
    # Migrate group
    CommandMetadata(
        path="migrate status",
        summary="Show migration status and available migrations.",
        audience="both",
        effect="read",
        requires_workspace=False,
    ),
    CommandMetadata(
        path="migrate plan",
        summary="Generate a migration plan without applying it.",
        audience="agent",
        effect="read",
        targeting="migration-name",
    ),
    CommandMetadata(
        path="migrate apply",
        summary="Apply a validated migration plan.",
        audience="agent",
        effect="workspace-write",
        targeting="migration-name",
    ),
    CommandMetadata(
        path="migrate recover",
        summary="Recover from an interrupted migration.",
        audience="agent",
        effect="workspace-write",
    ),
    CommandMetadata(
        path="migrate cleanup",
        summary="Clean up legacy source after migration.",
        audience="agent",
        effect="workspace-write",
        targeting="migration-name",
    ),
)

# Build the inventory (validates no duplicates or shadow conflicts).
COMMAND_INVENTORY = CommandInventory(_COMMANDS)


def assert_no_registration_drift(registered_paths: set[str]) -> None:
    """Assert that all canonical commands are registered and vice versa.

    Args:
        registered_paths: Set of command paths actually registered in Typer.

    Raises:
        AssertionError with details if drift is detected.
    """
    metadata_paths = {entry.path for entry in COMMAND_INVENTORY.entries}
    missing_registration = metadata_paths - registered_paths
    missing_metadata = registered_paths - metadata_paths
    errors = []
    if missing_registration:
        errors.append(f"Commands with metadata but no registration: {sorted(missing_registration)}")
    if missing_metadata:
        errors.append(f"Commands registered but with no metadata: {sorted(missing_metadata)}")
    if errors:
        raise AssertionError("; ".join(errors))
