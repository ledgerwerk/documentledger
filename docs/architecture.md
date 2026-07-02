# Architecture

## Configuration and workspace loading

Documentledger discovers `documentledger.toml` or `.documentledger.toml` by walking upward from the current directory. The loaded configuration defines the project metadata, storage directory, scan roots, allowed file extensions, validation commands, and policy flags.

A workspace combines the loaded configuration with storage metadata from `.documentledger/storage.yaml`. Commands that require an initialized workspace fail with a structured `workspace_not_found` error when no config is found, or a `storage_missing` error when the config exists but storage metadata is absent. `status` distinguishes three states explicitly: `uninitialized` (no config), `config_only` (config without storage metadata), and `initialized` (both present).

## Storage model

The storage layer writes YAML files only through the Documentledger APIs:

- `.documentledger/storage.yaml` stores schema metadata, project UUID, the current `state_version`, the next scan number, and the latest scan id.
- `.documentledger/scans/scan-NNNN.yaml` stores source hashes, document hashes, changed sources, deleted sources, stale docs, unlinked changed sources, and a scan record `version`.
- `.documentledger/docs/*.yaml` stores document records with linked sources, freshness metadata, notes, and a doc-record `version`.
- `.documentledger/rendered/latest-context.md` is a regenerated cache of the latest rendered update context.

Scan ids are formatted as `scan-0001`, `scan-0002`, and so on.

The recommended commit policy is to version `storage.yaml`, `scans/*.yaml`, and `docs/*.yaml` as the source of truth, and to ignore `rendered/` because it is regenerated on demand.

State is hash- and version-based. Timestamps are intentionally absent from persisted storage and rendered context front matter.

## Path identity

All user supplied doc and source paths are normalized as repository-relative POSIX paths. Absolute paths, backslash paths, empty paths, `.` paths, and paths containing `..` are rejected. Document record filenames are derived from the documentation path slug plus a short SHA-256 digest, so records remain filesystem-safe while preserving unique document identities.

## Scanning algorithm

The scanner collects files under the configured source roots and documentation roots. It skips storage files, excluded directories such as `.git`, `__pycache__`, `build`, `dist`, virtual environments, and files whose extensions are not configured.

Each collected file is hashed with SHA-256. On the first scan, Documentledger records a clean baseline. On later scans it compares current source hashes with the previous scan:

- Current paths with missing or different previous hashes become changed sources.
- Previous source paths missing from the current set become deleted sources.
- Changed or deleted sources are mapped through document link records to produce stale docs.
- Changed sources with no link record are reported as unlinked changed sources.

## Link management

A document link connects one documentation file to one source file. `links add` validates both paths, creates the document record if needed, stores a sorted unique source list, and optionally updates notes with the supplied reason. `links remove` removes one source path from an existing document record. Staleness is computed only across these links, so precise links keep the selective-update model useful.

## Context rendering

`docs stale` returns structured stale details for the latest scan. `docs build-context` renders a Markdown context document with stale docs, linked changed and deleted sources, unlinked changed sources, configured validation commands, and agent rules. The context can be written to `.documentledger/rendered/latest-context.md`, written to a chosen output path, printed, or both.

The `--include-unlinked` flag adds a bootstrap section that lists every source file with no linked documentation. This is intended for first-time documentation passes in repositories that do not yet have a link graph. The bootstrap section is computed as the set of source files recorded in the latest scan minus the set of sources referenced by any doc record.

## Freshness marking

`mark-fresh` requires a latest scan and a non-empty reason. It can update one selected document or all stale docs. For each document it stores the latest scan id, hashes the current document content, updates the doc record content when needed, and records the reason in the document record.

By default `mark-fresh` rejects documents that have no linked sources with an `unlinked_doc` error. This prevents tracking a document that can never become stale from source changes. The `--allow-unlinked` option overrides the check for intentionally unlinked documents and records the reason with an `(intentionally unlinked)` marker.

## CLI structure and errors

The Typer CLI exposes top-level commands for initialization, status, doctor checks, scans, and freshness marking. Nested command groups handle links and docs.

Error handling is centralized through a per-command error decorator. Each command callback is wrapped so that a `DocumentledgerError` is rendered with the real command name. With `--json`, the CLI emits a stable envelope with `ok`, `command`, `error` (code, message, remediation), and `events`. Without `--json`, it prints a concise human-readable `Error:` message and remediation hints. `DocumentledgerError` is a plain exception rather than a Click exception, which keeps command names accurate and lets the CLI choose the output format.

## ledgercore integration

`ledgercore>=0.2` is an active dependency. Documentledger uses ledgercore for YAML storage, atomic writes, config discovery, path validation, scan-id and doc-record identity helpers, and SHA-256 hashing.
