# Usage

This page is the task-oriented workflow. See [CLI reference](cli.md) for every option and result shape.

<!-- docledger-section: initialize-a-workspace -->

## Initialize

From the repository root, initialize the shared ledger layout:

```bash
documentledger init --project-name example
```

Initialization creates `.ledger/ledger.toml`, the Documentledger tool config, the project `data` mount, and the cache `artifacts` mount.

<!-- docledger-section: check-workspace-status -->

## Inspect status and next action

```bash
documentledger --json status
documentledger --json doctor
documentledger --json next-action
```

`uninitialized` means no resolvable canonical project or its required metadata, not simply that a legacy root TOML file is absent. Diagnostics distinguish missing bindings, missing data, invalid configuration, and link/index problems.

<!-- docledger-section: scan-source-and-documentation-files -->

## Scan

```bash
documentledger --json scan
```

The first scan is a clean baseline. Later scans compare deterministic SHA-256 file and source-unit hashes and report changed/deleted sources, affected sections, unlinked changed sources, and unmapped changed units. An unchanged scan reuses its version and does not rewrite state.

<!-- docledger-section: inspect-document-and-source-inventory -->

## Inspect documents and source units

```bash
documentledger document list
documentledger document sections --all --outline
documentledger source list --ids-only --path-prefix documentledger
documentledger source show SOURCE_ID
```

Use stable section ids and source-unit ids for precise links. Cursor, selector, and path validation failures are reported before state changes.

<!-- docledger-section: link-documentation-to-sources -->

## Add broad and precise links {#link-documentation-to-sources}

Prefer section-to-source-unit edges:

```bash
documentledger link add-section \
  --doc docs/usage.md \
  --section usage-scan \
  --source-unit py:function:documentledger/commands/root.py::scan \
  --coverage cli-command \
  --impact behavior \
  --reason "Documents scan behavior."
```

Use `documentledger link add --doc DOC --source SOURCE` only when a whole-file edge is intentionally broad. Review links with `documentledger link list` and remove them with the matching remove command.

<!-- docledger-section: propose-import-and-audit-links -->

## Propose, import, and audit links

```bash
documentledger link propose --all-docs --out-dir /tmp/documentledger-maps
documentledger --json link import-map --directory /tmp/documentledger-maps --check-and-apply
documentledger --json link audit
documentledger --json coverage
```

Proposal files are deterministic suggestions. Review them before applying a batch; `--check-and-apply` validates the complete batch before one logical write.

<!-- docledger-section: find-and-update-stale-documentation -->

## Build context, update, and validate

```bash
documentledger document affected
documentledger document build-context --affected --out /tmp/documentledger-context.md
```

Edit affected sections, run configured validation commands, and inspect the resulting links and errors. Context is bounded by source lines, section lines, and total bytes and includes a truncation manifest when limits apply.

<!-- docledger-section: mark-documentation-fresh -->

## Mark fresh

```bash
documentledger document mark-fresh \
  --doc docs/usage.md \
  --section usage-scan \
  --reason "Updated after scan version VERSION."
```

Mark fresh only after validation. Section-level marking updates the live affected projection without requiring another scan. Unlinked documents are rejected unless `--allow-unlinked` is explicitly appropriate.

`--all` selects all configured documents; `--affected` selects only currently affected documents. For bootstrap, use `--all --allow-unlinked` only after reviewing coverage and explicitly accepting any remaining unlinked documents.

<!-- docledger-section: json-and-human-output -->

## JSON, human, and profile output

Put `--json` before a command for the stable machine envelope. Omit it for concise human output. `--profile` adds deterministic operation events and durations to JSON output for diagnosis. `documentledger --version`, `commands`, and `help COMMAND_PATH...` work without a workspace.

Commit canonical project metadata and durable `data` records according to the repository policy. Cache `artifacts` output is derived and normally ignored. Do not edit ledger records manually.

<!-- docledger-section: ledger-state-and-commit-policy -->

## Ledger state and commit policy

Commit `.ledger/ledger.toml`, the tool configuration, and durable `data` records according to repository policy. Cache `artifacts` output is derived. Historical scan state is supplied by Git history, not a persisted scans directory.

<!-- docledger-section: storage-commands -->

## Storage commands

Use `documentledger storage where` to inspect resolved mounts and `documentledger storage validate --strict` to validate canonical bindings. Migration is explicit and is documented separately.

<!-- docledger-section: validate-ledger-state -->

## Validate ledger state

Run `documentledger --json doctor`, `documentledger --json link audit`, and `documentledger --json check` before committing documentation updates.

<!-- docledger-section: bootstrapping-a-new-repository -->

## Bootstrapping a new repository

For a new project, run `documentledger init`, create the first baseline with `documentledger --json scan`, and follow the dedicated [bootstrap workflow](bootstrap.md).

<!-- docledger-section: usage-limitations -->

## Limitations

Freshness is routed through explicit links and hash dimensions; an unlinked source change cannot identify a section. Git history replaces persisted historical scan files. The configured roots and extensions are intentionally static.

:::{deprecated} 0.6
`docledger`, the plural command groups, root `mark-fresh`, and legacy storage migration wrappers are compatibility-only. New automation must use `documentledger` and canonical singular command paths.
:::
