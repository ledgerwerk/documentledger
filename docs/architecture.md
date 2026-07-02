# Architecture

<!-- docledger-section: architecture-configuration-and-workspace-loading -->

## Configuration and workspace loading

Documentledger discovers `documentledger.toml` or `.documentledger.toml` by walking upward from the current directory. The loaded configuration defines the project metadata, storage directory, scan roots, allowed file extensions, validation commands, and policy flags.

A workspace combines the loaded configuration with storage metadata from `.documentledger/storage.yaml`. Commands that require an initialized workspace fail with a structured `workspace_not_found` error when no config is found, or a `storage_missing` error when the config exists but storage metadata is absent. `status` distinguishes three states explicitly: `uninitialized` (no config), `config_only` (config without storage metadata), and `initialized` (both present).

When storage metadata exists, loading the workspace normalizes the persisted state to the current storage schema version. Timestamp keys are stripped from metadata and records, the single current scan record is normalized to the current v4 schema when present, doc records are rewritten to the current v4 schema, and missing `version` or `state_version` fields are filled in.

<!-- docledger-section: architecture-storage-model -->

## Storage model

The storage layer writes YAML files only through the Documentledger APIs:

- `.documentledger/storage.yaml` stores schema metadata, project UUID, and the current `state_version`.
- `.documentledger/scan.yaml` stores the current source hashes, document hashes, source-unit inventory, unit deltas, affected-section snapshots, stale-doc projections, unlinked changed sources, unmapped changed units, and the monotonic current scan `version`.
- `.documentledger/docs/*.yaml` stores document records with `sections[].links[]`, derived `linked_sources`, section hashes, tracked source-unit hashes, freshness metadata including `last_fresh_scan_version`, notes, and a doc-record `version`.
- `.documentledger/rendered/latest-context.md` is a regenerated cache of the latest rendered update context.

Git history is the record of older scan baselines. `.documentledger/scans/` does not exist in the v4 storage model.

The recommended commit policy is to version `storage.yaml`, `scan.yaml`, and `docs/*.yaml` as the source of truth, and to ignore `rendered/` because it is regenerated on demand.

State is hash- and version-based. Timestamps are intentionally absent from persisted storage and rendered context front matter.

<!-- docledger-section: architecture-path-identity -->

## Path identity

All user supplied doc and source paths are normalized as repository-relative POSIX paths. Absolute paths, backslash paths, empty paths, `.` paths, and paths containing `..` are rejected. Document record filenames are derived from the documentation path slug plus a short SHA-256 digest, so records remain filesystem-safe while preserving unique document identities.

Source units and doc sections use stable semantic ids rather than line-number identities. For Python, ids look like `py:function:documentledger/cli.py::doctor`. For Markdown, ids look like `md:section:docs/usage.md::usage-validate-ledger-state`.

<!-- docledger-section: architecture-scanning-algorithm -->

## Scanning algorithm

The scanner collects files under the configured source roots and documentation roots. It skips storage files, excluded directories such as `.git`, `__pycache__`, `build`, `dist`, virtual environments, and files whose extensions are not configured. Documentation files are parsed into stable sections from Markdown headings and optional `docledger-section` markers; files without headings still receive a whole-document section id.

Each collected file is hashed with SHA-256. Python source files are also parsed into source units: a file fallback unit, a module unit, and any top-level functions, classes, and methods. Each source unit carries separate hashes for signatures, decorators, bodies, docstrings, public contract, and exact content. Public contract hashes include semantic details such as exported assignments and public literal values so section links can track meaningful API behavior instead of only raw file bytes.

On the first scan, Documentledger records a clean baseline. On later scans it compares current source hashes and source-unit hashes with the previous scan:

- Current paths with missing or different previous hashes become changed sources.
- Previous source paths missing from the current set become deleted sources.
- Changed or deleted source units are resolved through section links to produce affected sections.
- `stale_docs` remains available as a compatibility projection of the docs that still contain affected sections.
- Changed sources with no link record are reported as unlinked changed sources.
- Changed units with no matching section link are reported as unmapped changed units.
- If every source and documentation hash matches the previous scan, `.documentledger/scan.yaml` is not rewritten, the previous scan version is reused, and the result reports `unchanged` as true.

<!-- docledger-section: architecture-link-management -->

## Link management

A document link is usually a section edge: one documentation section linked to one source unit plus a coverage type, impact type, reason, and tracked hash set. `links add-section` validates the doc, section, and source unit, then records tracked hashes based on the coverage defaults. `links import-map` lets an agent apply a validated mapping proposal without editing `.documentledger/` directly.

`links audit` checks stored section links for missing sections, missing source units, and duplicate edges. `links add` and `links remove` remain as broad-file fallback commands. They store whole-doc fallback links that track the file fallback unit, which is still useful for unparseable sources or intentionally coarse docs.

<!-- docledger-section: architecture-context-rendering -->

## Context rendering

`docs affected` computes a live affected-section projection from the latest scan and the current doc records. This means section-level `mark-fresh` can clear affectedness without requiring a follow-up scan.

`docs build-context` renders a Markdown context document with only the affected sections, their linked changed source units, current relevant source snippets, unlinked changed sources, configured validation commands, and agent rules. The context can be written to `.documentledger/rendered/latest-context.md`, written to a chosen output path, printed, or both.

The `--include-unlinked` flag adds a bootstrap section that lists every source file with no linked documentation. This is intended for first-time documentation passes in repositories that do not yet have a link graph. The bootstrap section is computed as the set of source files recorded in the latest scan minus the set of sources referenced by any doc record.

<!-- docledger-section: architecture-freshness-marking -->

## Freshness marking

`mark-fresh` requires a latest scan and a non-empty reason. It can update one selected section, one selected doc, or all currently affected docs. For each selected section it stores the current section hash, refreshes the tracked source-unit hashes for that section's links, updates the latest scan version and document hash, and records the reason in the document record.

By default `mark-fresh` rejects documents that have no linked sources with an `unlinked_doc` error. This prevents tracking a document that can never become stale from source changes. The `--allow-unlinked` option overrides the check for intentionally unlinked documents and records the reason with an `(intentionally unlinked)` marker.

<!-- docledger-section: architecture-cli-structure-and-errors -->

## CLI structure and errors

The Typer CLI exposes top-level commands for initialization, status, doctor checks, scans, and freshness marking. Nested command groups handle links, docs, and source-unit inspection.

Error handling is centralized through a per-command error decorator. Each command callback is wrapped so that a `DocumentledgerError` is rendered with the real command name. With `--json`, the CLI emits a stable envelope with `ok`, `command`, `error` (code, message, remediation), and `events`. Without `--json`, it prints a concise human-readable `Error:` message and remediation hints. `DocumentledgerError` is a plain exception rather than a Click exception, which keeps command names accurate and lets the CLI choose the output format.

## ledgercore integration

`ledgercore>=0.2` is an active dependency. Documentledger uses ledgercore for YAML storage, atomic writes, config discovery, path validation, doc-record identity helpers, and SHA-256 hashing.
