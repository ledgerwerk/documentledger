# Usage

## Initialize a workspace

Run initialization from the repository root:

```bash
docledger init
```

By default this creates `documentledger.toml` and a `.documentledger/` storage directory. Use `--project-name` to set the project name, `--documentledger-dir` to choose another storage path, or `--hidden-config` to create `.documentledger.toml` instead.

## Check workspace status

```bash
docledger --json status
```

Status reports the workspace `state`:

- `uninitialized`: no `documentledger.toml` was found.
- `config_only`: a config file exists but `.documentledger/storage.yaml` is missing. Re-run `docledger init` from the project root to create the storage metadata.
- `initialized`: both config and storage metadata exist.

The `initialized` field is `true` only in the fully initialized state. The result also reports `storage_present`, the config path, the storage directory, the project name, the project UUID, and the latest scan id.

## Scan source and documentation files

```bash
docledger --json scan
```

A scan collects files from the configured source and documentation roots, hashes them, compares source hashes to the previous scan, and stores a new `scan-NNNN` record. The first scan establishes a baseline and does not report changed, deleted, stale, or unlinked sources.

Later scans report:

- `changed_sources`, source files whose hash changed or that are new since the previous scan.
- `deleted_sources`, source files that were present in the previous scan and are now gone.
- `stale_docs`, linked documentation files affected by changed or deleted sources.
- `unlinked_changed_sources`, changed source files that do not have documentation links.

## Link documentation to sources

```bash
docledger links add --doc docs/usage.md --source documentledger/cli.py --reason "Documents CLI workflow."
```

Links use repository-relative POSIX paths. Document paths must have configured documentation extensions, source paths must have configured source extensions, and both paths must exist. Adding the same link more than once is idempotent. Keep links precise: staleness is computed only across these links, so broadly linking every doc to every source makes too many docs stale for small changes.

List and remove links with:

```bash
docledger links list
docledger links remove --doc docs/usage.md --source documentledger/cli.py
```

## Find and update stale documentation

```bash
docledger --json docs stale
docledger docs build-context --all --print
```

The stale report contains each stale document with the linked changed and deleted sources that require inspection. The rendered context also lists unlinked changed sources and configured validation commands, so an agent knows both what to rewrite and how to validate the result.

## Bootstrapping a new repository

A fresh repository has no links yet, so the first scan reports no stale docs. To drive an initial documentation pass, include sources that have no documentation link:

```bash
docledger init
docledger scan
docledger docs build-context --all --include-unlinked --print
```

The `--include-unlinked` flag adds a bootstrap section that lists every source file with no linked documentation. Create docs for those sources, add links with `docledger links add`, scan again, validate, then mark the docs fresh. See [Bootstrap](bootstrap.md) for the full setup sequence.

## Mark documentation fresh

After updating and validating a stale document, mark it fresh:

```bash
docledger mark-fresh --doc docs/usage.md --reason "Docs updated after scan scan-0002."
```

`mark-fresh` records the latest scan id and the current document hash in the document record. It requires a non-empty reason. Use `--all` to mark every stale doc from the latest scan.

Unlinked docs are rejected by default:

```bash
docledger mark-fresh --doc docs/index.md --reason "Navigation page."        # rejected: unlinked_doc
docledger mark-fresh --doc docs/index.md --allow-unlinked --reason "Navigation page."
```

This prevents silently tracking a doc that can never become stale from source changes. Pass `--allow-unlinked` only for intentionally unlinked docs; the record stores the reason with an `(intentionally unlinked)` marker.

## Validate ledger state

```bash
docledger doctor
```

Doctor checks storage schema metadata, document record paths, duplicate links, missing documentation files, and missing source files.

## JSON and human output

Pass `--json` before the command to emit a stable JSON envelope:

```json
{"ok": true, "command": "status", "result": {}, "events": []}
```

Errors also use a JSON envelope when `--json` is set, and the envelope preserves the real command name:

```json
{"ok": false, "command": "scan", "error": {"code": "workspace_not_found", "message": "...", "remediation": []}, "events": []}
```

Without `--json`, commands print human-readable output and errors print concise `Error:` messages with remediation hints.

## Ledger state and commit policy

Documentledger stores its own state under the configured `.documentledger/` directory. The recommended commit policy for a documentation freshness ledger is:

- Commit `.documentledger/storage.yaml`, `.documentledger/scans/*.yaml`, and `.documentledger/docs/*.yaml`. These are the source of truth for project identity, scan history, and doc records with their links and freshness markers.
- Ignore `.documentledger/rendered/`. Rendered context is regenerated on demand by `docs build-context`.

Do not edit `.documentledger/` files directly; use the `docledger` commands so the records stay consistent.
