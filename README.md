# Documentledger

Documentledger is a documentation freshness ledger for coding-agent workflows. It records repository scans, maps documentation files to source files, reports stale documentation when linked source files change or disappear, and renders update context that tells an agent exactly which docs to inspect and rewrite.

It is designed to keep documentation honest: every documentation file is linked to the source files it describes, and a scan marks those docs stale the moment their linked sources change.

## Status

**Alpha.** Documentledger is usable for internal documentation maintenance and is approaching a first release. The CLI surface, storage schema, and link model are stable enough to rely on, but breaking changes are still possible before 1.0.

## Install

```bash
pip install -e .
```

This exposes the `docledger` console script. Documentledger requires Python 3.10 or newer.

> `ledgercore>=0.2` is declared as a **reserved dependency**. It is not imported yet; shared identity/config/storage primitives from `ledgercore` are planned for integration in a near-term release. It is kept in the dependency list intentionally so the integration is a code change, not a packaging change.

## Quickstart

From the root of a repository:

```bash
docledger init
docledger --json status
docledger --json scan
docledger links add --doc docs/usage.md --source src/cli.py --reason "Documents the CLI workflow."
docledger --json docs stale
docledger docs build-context --all --print
```

After updating and validating a stale document, mark it fresh:

```bash
docledger mark-fresh --doc docs/usage.md --reason "Docs updated after scan scan-0001."
```

## Workflow

1. **Initialize.** `docledger init` creates `documentledger.toml` and a `.documentledger/` storage directory.
2. **Scan.** `docledger scan` hashes source and documentation files under the configured roots. The first scan establishes a baseline; later scans report changed sources, deleted sources, stale docs, and unlinked changed sources.
3. **Link.** `docledger links add --doc DOC --source SOURCE` connects a documentation file to a source file. Staleness is computed only across these links, so keep them precise.
4. **Find stale docs.** `docledger docs stale` lists documentation whose linked sources changed or disappeared.
5. **Build update context.** `docledger docs build-context --all --print` renders the stale docs, their linked changed/deleted sources, unlinked changed sources, and the configured validation commands.
6. **Update and validate.** Rewrite only the stale docs, then run the validation commands.
7. **Mark fresh.** `docledger mark-fresh --doc DOC --reason "..."` records the scan id and current doc hash. Unlinked docs are rejected by default; pass `--allow-unlinked` only for intentionally unlinked docs.

## Bootstrapping a new repository

A fresh repository has no links yet, so the first scan reports no stale docs. To drive an initial documentation pass, include sources that have no documentation link:

```bash
docledger init
docledger scan
docledger docs build-context --all --include-unlinked --print
```

The bootstrap section lists every source file that has no linked documentation. Create docs for them, add links with `docledger links add`, scan again, validate, then mark the docs fresh.

## Commands

| Command | Purpose |
| --- | --- |
| `docledger init` | Create config and storage metadata. |
| `docledger status` | Report workspace state: `uninitialized`, `config_only`, or `initialized`. |
| `docledger doctor` | Validate storage schema, doc records, and link integrity. |
| `docledger scan` | Record a new scan and compute changes. |
| `docledger links list` / `add` / `remove` | Manage doc-to-source links. |
| `docledger docs list` / `stale` / `build-context` | Inspect docs and render update context. |
| `docledger mark-fresh` | Record that a doc matches the latest scan. |

Pass `--json` before any command to emit a stable JSON envelope. Without `--json`, commands print human-readable output, and errors print concise `Error:` messages (use `--json` for machine-readable error envelopes).

## Limitations

- Staleness is driven entirely by source-file hash changes routed through explicit links. Docs without links never become stale from source changes.
- `mark-fresh` is rejected for unlinked docs by default to prevent silently tracking a doc that can never go stale. Use `--allow-unlinked` for intentionally unlinked docs.
- Source and documentation roots are configured statically in `documentledger.toml`; there is no per-path ignore configuration yet.
- `ledgercore>=0.2` is a reserved dependency (see Install).

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
