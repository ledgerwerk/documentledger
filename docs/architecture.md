# Architecture

<!-- docledger-section: configuration-and-workspace-loading -->

## Canonical project resolution

Documentledger resolves the repository through ledgercore's schema-3 `.ledger/ledger.toml` manifest. The manifest registers the tool and supplies project identity and mount routing. `.ledger/documentledger/config.toml` contains only tool-owned configuration version 2. Legacy root TOML files are migration inputs, not normal discovery.

<!-- docledger-section: architecture-command-registration -->

## Command registration and metadata

Typer command modules register the canonical singular `document`, `source`, and `link` groups plus configuration, schema, storage, and migration groups. `COMMAND_INVENTORY` supplies stable summaries, effects, audience, workspace requirements, targeting, and aliases. The CLI reference generator traverses Click objects directly and checks catalog drift.

<!-- docledger-section: cli-structure-and-errors -->

## CLI state and result envelopes

Global options create a command state containing root, JSON, profile, and warnings. A centralized error wrapper preserves the real command path and renders either human output or a stable JSON envelope with `ok`, `command`, `result` or `error`, and `events`.

<!-- docledger-section: architecture-configuration -->

## Configuration parsing

`documentledger.config` validates the exact version-2 TOML shape, rejects unknown fields, normalizes arrays of strings, and produces typed `ToolConfig` values. Project identity, UUID, and mounts remain ledgercore concerns.

<!-- docledger-section: storage-model -->

## Storage and atomic state transitions

Storage writers validate schema constants, strip timestamp keys, increment integer state versions, and use atomic writes. Durable data includes `storage.yaml`, `scan.yaml`, `source-index.json`, and document records under `docs/*.yaml`. Rendered context and proposals use the resolved cache `artifacts` mount. Read-only commands validate state without repairing or rewriting it.

<!-- docledger-section: scanning-algorithm -->

## Scanning and source-unit identity

The scanner collects configured roots, filters excluded directories and extensions, hashes files, and indexes Python modules, functions, classes, methods, and fallback units. Source-unit identity is semantic and repository-relative; hash dimensions distinguish exact content, signatures, decorators, bodies, docstrings, and public contract.

<!-- docledger-section: path-identity -->

## Markdown sections and markers

The document index parses Markdown headings outside fenced code blocks and creates stable section ids, heading paths, line spans, summaries, and hashes. Explicit `docledger-section` markers provide semantic ids that survive wording and line-number changes.

<!-- docledger-section: link-management -->

## Link graph and tracked hashes

Section links connect document sections to source units with coverage, impact, reason, and tracked hash sets. Broad document-to-file edges remain a fallback. Audits detect missing sections, missing units, duplicate edges, and invalid records.

<!-- docledger-section: context-rendering -->

## Affectedness and context

Incremental scans compare the current source index to the prior baseline. Changed or deleted linked units resolve to affected sections; unlinked changed sources and unmapped units are reported separately. Context rendering selects bootstrap, affected, all, or doc/section modes and emits truncation metadata when bounds apply.

<!-- docledger-section: architecture-migration-boundary -->

## Migration boundary

Migration plans inspect legacy state, copy and verify files, validate plan digests, optionally adopt project identity, and activate the shared manifest last. Journals support recovery. Cleanup is a separate explicit operation.

<!-- docledger-section: freshness-marking -->

## Persistence and testing boundaries

All persisted state is deterministic, versioned, atomic, and timestamp-free. Unit tests cover parsing, storage, scanning, links, rendering, migration, CLI envelopes, and read-only invariants. Documentation tests cover requirements, generated CLI drift, page reachability, markers, links, API imports, and changelog ownership.

<!-- docledger-section: canonical-storage -->

## ledgercore integration

Documentledger requires `ledgercore>=0.6.0,<0.7.0` for shared schema-3 project authority, storage bindings, path handling, atomic writes, and hashing. The application owns its tool config and domain records while ledgercore owns shared project identity and mount resolution.
