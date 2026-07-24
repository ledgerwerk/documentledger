# Usage

<!-- docledger-section: usage-initialize-workspace -->

## Initialize a workspace

Run initialization from the repository root:

```bash
docledger init
```

By default this creates `documentledger.toml` and a `.documentledger/` storage directory. Use `--project-name` to set the project name, `--documentledger-dir` to choose another storage path, or `--hidden-config` to create `.documentledger.toml` instead.

<!-- docledger-section: usage-check-workspace-status -->

## Check workspace status

```bash
docledger --json status
```

Status reports the workspace `state`:

- `uninitialized`: no `documentledger.toml` was found.
- `bootstrap_required`: there is no baseline scan yet, or there is a baseline but no usable doc links.
- `incremental_clean`: the latest scan has no affected linked sections.
- `incremental_affected`: the latest scan has affected linked sections that should be reviewed.
- `mapping_incomplete`: changed source files are not yet fully linked to documentation.

The result also reports `recommended_command`, `recommended_reason`, compact latest-scan counts, and any root-layout diagnostics that should be fixed before trusting a baseline.

<!-- docledger-section: usage-run-scan -->

## Scan source and documentation files

```bash
docledger --json scan
```

A scan collects files from the configured source and documentation roots, hashes them, indexes Python source units, and compares the current state to the previous scan. The first scan establishes a baseline and does not report changed, deleted, stale, or unlinked sources.

Later scans report:

- `unchanged`, `true` when the source and documentation hashes match the previous scan exactly. No scan state is rewritten, no source files are re-indexed, and the previous scan version is reused; the human output prints `No tracked file changes since scan version <version>` instead of `Recorded scan version <version>`.
- `changed_sources`, source files whose hash changed or that are new since the previous scan.
- `changed_units`, source units whose tracked semantic hashes changed. For Python this is usually the changed function, method, class, or module contract rather than the whole file.
- `deleted_sources`, source files that were present in the previous scan and are now gone.
- `affected_sections`, the documentation sections currently impacted by changed or deleted linked source units.
- `stale_docs`, a compatibility projection of the docs that still contain affected sections.
- `unlinked_changed_sources`, changed source files that do not have documentation links.

<!-- docledger-section: usage-link-documentation-to-sources -->

## Link documentation to sources

```bash
docledger links add --doc docs/usage.md --source documentledger/cli.py --reason "Documents CLI workflow."
```

Whole-file links remain available as a broad fallback, but precise section links are the default:

```bash
docledger links add-section \
  --doc docs/usage.md \
  --section usage-validate-ledger-state \
  --source-unit py:function:documentledger/cli.py::doctor \
  --coverage cli-command \
  --impact behavior \
  --reason "Documents the doctor command."
```

Links use repository-relative POSIX paths. Document paths must have configured documentation extensions, source paths and source units must exist, and coverage and impact values are validated. Keep links precise: section-level links let small command changes affect only the doc sections that actually describe them.

List and remove links with:

```bash
docledger links list
docledger links remove --doc docs/usage.md --source documentledger/cli.py
docledger links remove-section --doc docs/usage.md --section usage-validate-ledger-state --source-unit py:function:documentledger/cli.py::doctor
docledger links import-map --file /tmp/documentledger-map.yaml --validate
docledger links import-map --directory /tmp/documentledger-maps --check-and-apply
```

<!-- docledger-section: usage-find-and-update-stale-documentation -->

## Find and update stale documentation

```bash
docledger --json docs affected
docledger docs build-context --affected --out /tmp/docledger-context.md
```

`docs affected` reports the live affected sections for the latest scan. After a section is updated and marked fresh, it disappears from `docs affected` immediately; a follow-up scan is optional confirmation, not the only way to clear affectedness.

The rendered context contains only the affected doc sections, their linked changed source units, the current relevant source snippets, unlinked changed sources, and configured validation commands. Inspect the affected sections and linked changed source units first. Expand to whole files only when the changed unit cannot be understood in isolation.

<!-- docledger-section: usage-bootstrapping-a-new-repository -->

## Bootstrapping a new repository

A fresh repository has no links yet, so the first scan reports no stale docs. To drive an initial documentation pass, use the explicit bootstrap flow:

```bash
docledger init
docledger scan
docledger docs build-context --bootstrap --out /tmp/docledger-bootstrap.md
docledger links propose --all-docs --out-dir /tmp/docledger-maps
docledger --json links import-map --directory /tmp/docledger-maps --check-and-apply
```

The bootstrap context and proposal flow give agents a deterministic first-pass link graph without applying anything until the full batch validates. See [Bootstrap](bootstrap.md) for the full setup sequence.

<!-- docledger-section: usage-mark-documentation-fresh -->

## Mark documentation fresh

After updating and validating an affected section, mark it fresh:

```bash
docledger mark-fresh --doc docs/usage.md --section usage-validate-ledger-state --reason "Docs updated after scan version 2."
```

`mark-fresh` records the latest scan version, the current document hash, the current section hash, and the tracked source-unit hashes for the selected links. It requires a non-empty reason. Use `--all` to mark every currently affected section from the latest scan, or `--doc` without `--section` to update all affected sections in one doc explicitly.

Unlinked docs are rejected by default:

```bash
docledger mark-fresh --doc docs/index.md --reason "Navigation page."        # rejected: unlinked_doc
docledger mark-fresh --doc docs/index.md --allow-unlinked --reason "Navigation page."
```

This prevents silently tracking a doc that can never become stale from source changes. Pass `--allow-unlinked` only for intentionally unlinked docs; the record stores the reason with an `(intentionally unlinked)` marker.

<!-- docledger-section: usage-validate-ledger-state -->

## Validate ledger state

```bash
docledger doctor
```

Doctor checks storage schema metadata, document record paths, suspicious root configuration, missing documentation files, missing source files, duplicate edges, missing source-unit ids, and missing section ids.

<!-- docledger-section: usage-json-and-human-output -->

## JSON and human output

Pass `--json` before the command to emit a stable JSON envelope:

```json
{ "ok": true, "command": "status", "result": {}, "events": [] }
```

Errors also use a JSON envelope when `--json` is set, and the envelope preserves the real command name:

```json
{
  "ok": false,
  "command": "scan",
  "error": {
    "code": "workspace_not_found",
    "message": "...",
    "remediation": []
  },
  "events": []
}
```

Without `--json`, commands print human-readable output and errors print concise `Error:` messages with remediation hints.

<!-- docledger-section: usage-ledger-state-and-commit-policy -->

## Ledger state and commit policy

Documentledger stores its own state under the configured `.documentledger/` directory. The recommended commit policy for a documentation freshness ledger is:

- Commit `.documentledger/storage.yaml`, `.documentledger/scan.yaml`, and `.documentledger/docs/*.yaml`. These are the source of truth for project identity, the current scan baseline, section-level links, tracked hash state, and freshness markers.
- Ignore `.documentledger/rendered/`. Rendered context is regenerated on demand by `docs build-context`.

Do not edit `.documentledger/` files directly; use the `docledger` commands so the records stay consistent.

## Storage commands

Use `docledger storage where` to inspect the active layout. Migrate a legacy workspace with a reviewed dry-run plan, then verify before any cleanup:

```bash
docledger storage migrate --dry-run --plan-file migration.json
docledger storage migrate --plan-file migration.json --adopt-project-uuid
docledger storage verify --strict
docledger storage cleanup-legacy --dry-run
```

Routine commands never migrate automatically and read-only commands do not initialize cache directories or repair bindings.
