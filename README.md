[![PyPI - Version](https://img.shields.io/pypi/v/documentledger)](https://pypi.org/project/documentledger/)
![PyPI - Python Version](https://img.shields.io/pypi/pyversions/documentledger)
![PyPI - Downloads](https://img.shields.io/pypi/dm/documentledger)

# Documentledger

Documentledger is a documentation freshness ledger for coding-agent workflows. It records repository scans, maps documentation sections to source units, reports affected documentation when linked source units change or disappear, and renders update context that tells an agent exactly which sections to inspect and rewrite.

It is designed to keep documentation honest: documentation sections are linked to the source units they describe, and a scan marks those sections affected when their tracked source units change.

## Status

**Alpha.** Documentledger is usable for internal documentation maintenance and is approaching a first release. The CLI surface, storage schema, and link model are stable enough to rely on, but breaking changes are still possible before 1.0.

## Install

```bash
pip install -e .
```

This exposes the `docledger` console script. Documentledger requires Python 3.10 or newer.

> `ledgercore>=0.5.0,<0.6.0` is an active dependency. Documentledger uses its schema-3 shared manifest, derived paths, bindings, atomic writes, YAML storage, path validation, and SHA-256 helpers.

## Quickstart

From the root of a repository:

```bash
docledger init
docledger --json status
docledger --json scan
docledger docs build-context --bootstrap
docledger links propose --all-docs
docledger --json links import-map --directory /tmp/docledger-maps --check-and-apply
docledger --json links audit
docledger --json coverage
```

After updating and validating an affected section, mark it fresh:

```bash
docledger mark-fresh --doc docs/usage.md --section usage-cli --reason "Docs updated after scan version 1."
```

## Workflow

1. **Initialize.** `docledger init` creates the shared schema-3 `.ledger/ledger.toml`, `.ledger/documentledger/config.toml`, project `data` storage, and cache `artifacts` mount.
2. **Scan.** `docledger scan` hashes source and documentation files under the configured roots, indexes only changed Python source files, persists `scan.yaml` and `source-index.json` below `.ledger/documentledger/data`, and rewrites state only when source or doc hashes change. Unchanged scans reuse the latest scan version and report `unchanged`.
3. **Link.** `docledger links add-section --doc DOC --section SECTION --source-unit SOURCE_UNIT` connects a documentation section to a source unit with coverage, impact, reason, and tracked hashes. `links add --doc DOC --source SOURCE` remains available as a broad-file fallback.
4. **Bootstrap and batch-link.** `docledger docs build-context --bootstrap`, `docledger links propose --all-docs`, and `docledger --json links import-map --directory DIR --check-and-apply` provide a deterministic bootstrap path; generated output defaults to the cache `artifacts` mount.
5. **Find affected sections.** `docledger docs affected` lists documentation sections whose linked source units changed or disappeared.
6. **Build update context.** `docledger docs build-context --affected --out FILE` renders the affected sections, linked changed source units, source snippets, unlinked changed sources, and configured validation commands.
7. **Update and validate.** Rewrite only the affected sections by default, then run the validation commands.
8. **Mark fresh.** `docledger mark-fresh --doc DOC --section SECTION --reason "..."` refreshes tracked source-unit hashes and section hashes in a versioned doc record. Unlinked docs are rejected by default; pass `--allow-unlinked` only for intentionally unlinked docs.

## Storage migration

Existing legacy workspaces are never migrated implicitly. Inspect and apply an explicit, copy-first plan:

```bash
docledger storage where
docledger storage migrate --dry-run --plan-file migration.json
docledger storage migrate --plan-file migration.json --adopt-project-uuid
docledger storage verify --strict
docledger storage cleanup-legacy --dry-run
```

Migration preserves the legacy config and data, verifies every copied regular file by SHA-256, updates the shared manifest last, and treats `source-index.json` as committed baseline state. Missing source indexes require explicit exact-hash repair; cleanup requires a completed migration journal and `--yes`.

## State model

Documentledger state is intentionally timestamp-free.

- `.ledger/documentledger/data/storage.yaml` stores `schema_version`, `project_uuid`, `state_version`, and the latest compact scan summary counts used by `status`.
- `.ledger/documentledger/data/scan.yaml` stores the current `documentledger.scan.v5` summary with source/doc hashes, source-index metadata, unit deltas, affected-section projections, stale-doc compatibility output, unmapped changed units, and monotonic scan `version`.
- `.ledger/documentledger/data/source-index.json` stores the current deterministic source-unit inventory and is committed source of truth.
- `.ledger/documentledger/data/docs/*.yaml` stores `documentledger.doc_record.v4` records with section links, tracked source-unit hashes, derived linked sources, freshness hashes, `last_fresh_scan_version`, notes, and integer `version` values.
- Rendered contexts and proposals are derived output below the resolved cache `artifacts` mount.

Freshness is hash-based only. Documentledger does not persist or compare legacy timestamp fields, `mtime`, or other date-based freshness markers.

## Bootstrapping a new repository

A fresh repository has no links yet, so the first scan reports no stale docs. To drive an initial documentation pass, use the explicit bootstrap flow:

```bash
docledger init
docledger --json scan
docledger docs build-context --bootstrap --out /tmp/docledger-bootstrap.md
docledger links propose --all-docs --out-dir /tmp/docledger-maps
docledger --json links import-map --directory /tmp/docledger-maps --check-and-apply
```

The bootstrap context lists every source file that has no linked documentation and the current doc inventory. Review or correct the generated proposal files, apply them as one validated batch, run `docledger --json links audit`, then validate and mark the docs fresh.

## Commands

| Command                                                                     | Purpose                                                                              |
| --------------------------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| `docledger init`                                                            | Create the canonical schema-3 shared layout and storage metadata.                    |
| `docledger storage where` / `migrate` / `verify` / `cleanup-legacy`         | Inspect, migrate, verify, and explicitly clean up legacy storage.                    |
| `docledger status`                                                          | Report workspace state, diagnostics, and the recommended next command.               |
| `docledger doctor`                                                          | Validate storage schema, doc records, and link integrity.                            |
| `docledger scan`                                                            | Record a new scan and compute changes.                                               |
| `docledger sources list` / `show`                                           | Inspect source-unit ids for precise section links with compact filters and cursors.  |
| `docledger links list` / `add-section` / `remove-section` / `import-map`    | Manage section-to-source-unit links and apply mapping batches atomically.            |
| `docledger links propose`                                                   | Generate deterministic bootstrap mapping proposals without applying them.            |
| `docledger links audit`                                                     | Check section links for missing sections, missing source units, and duplicate edges. |
| `docledger docs list` / `sections` / `affected` / `stale` / `build-context` | Inspect docs and render bounded update context to a file.                            |
| `docledger coverage`                                                        | Report doc/section/source coverage and obvious inventory gaps.                       |
| `docledger mark-fresh`                                                      | Record that a section or doc matches the latest scan.                                |

Pass `--json` before any command to emit a stable JSON envelope. Without `--json`, commands print human-readable output, and errors print concise `Error:` messages (use `--json` for machine-readable error envelopes).

## Limitations

- Freshness is driven by source-unit hash changes routed through explicit links. Docs without links never become affected from source changes.
- `mark-fresh` is rejected for unlinked docs by default to prevent silently tracking a doc that can never become affected. Use `--allow-unlinked` for intentionally unlinked docs.
- Source and documentation roots are configured statically in `documentledger.toml`; there is no per-path ignore configuration yet.

## Development

```bash
python -m pytest -q
python -m compileall -q documentledger tests
```

Documentation is built with Sphinx:

```bash
bash docs/build.sh
```

## License

Apache-2.0. See `LICENSE`.
