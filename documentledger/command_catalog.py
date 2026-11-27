"""Command metadata catalog for Documentledger.

Defines every canonical command and alias in a CommandInventory.
Used by: commands, help, generated CLI reference, drift tests.
"""

from __future__ import annotations

from typing import TypedDict

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
        path="review",
        summary="Review changed source, affected documentation, and safe exact mappings.",
        audience="agent",
        effect="workspace-write",
    ),
    CommandMetadata(
        path="finish",
        summary="Audit links, run configured validation, and record section freshness dispositions.",
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
        path="capabilities",
        summary="Report versioned features and the canonical command surface.",
        audience="agent",
        effect="read",
        requires_workspace=False,
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
        path="document validate",
        summary="Run configured validation and record a current-content attestation.",
        audience="agent",
        effect="workspace-write",
        targeting="validation-command",
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


class CommandReferenceDetails(TypedDict, total=False):
    extended_description: str
    json_result: str
    examples: tuple[str, ...]


COMMAND_REFERENCE_DETAILS: dict[str, CommandReferenceDetails] = {
    "init": {
        "extended_description": (
            "Initialization discovers source roots once and records them in configuration. "
            "Use repeatable `--source-root` options when detection is ambiguous or a different explicit set is required."
        ),
        "examples": (
            "documentledger init --project-name example",
            "documentledger init --source-root src/example --source-root tests",
        ),
    },
    "check": {
        "extended_description": (
            "Use `--complete` for the strict completion gate. It checks global role-aware mapping coverage, documentation navigation, "
            "freshness, link integrity, and current validation attestations."
        ),
        "examples": ("documentledger check --complete",),
    },
    "review": {
        "extended_description": (
            "Runs or reuses an incremental scan, proposes only exact policy-approved mappings, and reports affected sections "
            "and unresolved coverage gaps. Review does not mark sections fresh."
        ),
        "json_result": (
            "With `--json`, returns `documentledger.review.v1` with affected sections, relevant unmapped changes, mapping candidates, "
            "ignored changes, and a next action. Output arrays are bounded by default; `--details` removes the limits."
        ),
        "examples": (
            "documentledger review",
            "documentledger review --doc docs/api.md --details",
        ),
    },
    "finish": {
        "extended_description": (
            "Audits links, runs configured validation through the canonical verification pipeline, and records freshness only "
            "after all checks pass. Unchanged affected sections require an explicit review decision."
        ),
        "json_result": (
            "With `--json`, returns `documentledger.finish.v1` with freshness dispositions, link-audit state, and validation results. "
            "Validation failure or content mutation leaves freshness unchanged."
        ),
        "examples": (
            "documentledger finish",
            'documentledger finish --reviewed-no-change "docs/api.md#api=The claim remains accurate."',
            'documentledger finish --generated-verified "docs/api.md#reference=Generated output verified."',
        ),
    },
    "capabilities": {
        "extended_description": (
            "Probe this command before choosing optional automation. Each advertised capability is versioned and corresponds to "
            "an available workflow in the installed package."
        ),
        "json_result": (
            "Returns `documentledger.capabilities.v1`, the package version, storage schema, feature flags, versioned capability "
            "identifiers, and canonical command paths."
        ),
        "examples": ("documentledger --json capabilities",),
    },
    "document build-context": {
        "extended_description": (
            "Builds bounded source-backed context for bootstrap or documentation updates. When pagination is advertised, continue "
            "with `--cursor NEXT_CURSOR` until the result is not truncated; do not treat omitted evidence as reviewed."
        ),
        "examples": (
            "documentledger document build-context --affected --include-unlinked --out -",
            "documentledger --json document build-context --bootstrap --page-size 40 --out -",
        ),
    },
    "document validate": {
        "extended_description": (
            "Runs the configured documentation validation commands and records an attestation for the current source, documentation, "
            "configuration, and scan snapshot."
        ),
        "examples": ("documentledger document validate",),
    },
    "link import-map": {
        "extended_description": (
            "For manifest-owned proposal directories, review the scan-bound batch before applying it. `--check-and-apply` accepts "
            "only files recorded as reviewed. Standalone mapping files can be validated or applied separately."
        ),
        "examples": (
            "documentledger --json link import-map --directory ./proposals --review",
            "documentledger --json link import-map --directory ./proposals --check-and-apply",
            "documentledger --json link import-map --file ./mapping.yaml --validate",
        ),
    },
    "link propose": {
        "extended_description": (
            "Generates deterministic evidence-ranked mappings from a completed scan and writes a scan-bound manifest for the proposal "
            "batch. Documents without confident candidates remain represented in that manifest."
        ),
        "examples": ("documentledger link propose --all-docs --out-dir ./proposals",),
    },
    "coverage": {
        "extended_description": (
            "Reports global documentation and source coverage. Source units are grouped by role; only configured mapping-review roles "
            "block completion by remaining unlinked."
        ),
        "examples": ("documentledger --json coverage",),
    },
}


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
