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
documentledger --json capabilities
documentledger --json status
documentledger --json doctor
documentledger --json next-action
```

Probe `capabilities` before relying on optional workflow commands. Status distinguishes an `uninitialized` workspace from a ready workspace and includes a recommended next action. Its `state` is `bootstrap_required` when no baseline or links exist, `incremental_affected` when linked sections need updating, `mapping_incomplete` when relevant changed units have no mappings, and `incremental_clean` otherwise. The separate `freshness_state` and `mapping_state` fields describe those dimensions directly. Production changes trigger mapping review by default; test, private, and generated roles are ignored unless `mapping_review_roles` opts them in.

<!-- docledger-section: scan-source-and-documentation-files -->

## Scan

```bash
documentledger --json scan
```

The first scan is a clean baseline. Later scans compare deterministic SHA-256 file and source-unit hashes and report changed/deleted sources, affected sections, unlinked changed sources, and unmapped changed units. An unchanged scan reuses its version and does not rewrite scan state. Every scan also reconciles existing document records with the live Markdown index: new sections are added, surviving metadata is refreshed, and removed sections with no links are pruned. A removed linked section is retained as an actionable orphan.

<!-- docledger-section: inspect-document-and-source-inventory -->

## Inspect documents and source units

```bash
documentledger document list
documentledger document sections --all --outline
documentledger source list --ids-only --path-prefix documentledger
documentledger source show SOURCE_ID
```

Use stable section ids and source-unit ids for precise links. Cursor, selector, and path validation failures are reported before state changes.

(link-documentation-to-sources)=

<!-- docledger-section: link-documentation-to-sources -->

## Add broad and precise links

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

<!-- docledger-section: review-current-changes -->

## Review current changes

Use the capability-aware review command for the normal incremental path:

```bash
documentledger review
documentledger review --doc docs/usage.md
documentledger review --details
```

Review scans current files and returns a bounded summary of affected sections, relevant unmapped changes, mapping candidates, and the next action. Safe exact mappings may be applied automatically; ambiguous candidates remain review items. Resolve mappings deliberately with `link add-section` or reviewed `link import-map`. Use `--details` when full evidence arrays are needed. The lower-level `scan`, `document affected`, and `link propose` commands remain available for bootstrap and manual workflows.

<!-- docledger-section: find-and-update-stale-documentation -->

## Build context, update, and validate

```bash
documentledger document affected
documentledger document build-context --affected --out -
```

`--out -` streams raw Markdown directly to stdout without creating the default artifact or a file named `-`. Use `--out PATH` for an atomically written file. Do not combine raw streaming or `--print` with `--json`, because JSON mode emits exactly one machine-readable envelope.

Edit affected sections, run configured validation commands, and inspect the resulting links and errors. Context is bounded by source lines, section lines, and total bytes and includes a truncation manifest when limits apply.

<!-- docledger-section: mark-documentation-fresh -->

## Finish freshness

After editing, run `documentledger finish`. It checks mappings, audits links, runs configured validation commands, and writes section-level freshness dispositions only after every gate passes:

```bash
documentledger finish
documentledger finish --reviewed-no-change "docs/usage.md#usage-scan=The instructions remain accurate."
documentledger finish --generated-verified "docs/api.md#api-client=Generated reference verified."
```

Changed sections are recorded as `updated`. An unchanged affected section requires an explicit `reviewed-no-change` reason or `generated-verified` decision. If mapping review, link audit, or configured validation fails, freshness is not written. Review the returned results and finish with `documentledger --json status`.

For bootstrap and manual workflows, the lower-level freshness command remains available:

```bash
documentledger document mark-fresh --doc docs/usage.md --section usage-scan \
  --reason "Updated after scan version VERSION."
```

Section-level `mark-fresh` updates the live affected projection without another scan. `--all` selects all configured documents and `--affected` selects currently affected documents. Use `--allow-unlinked` only when intentionally accepting unlinked documents after reviewing coverage.

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

Run `documentledger finish` as the normal documentation gate, then inspect `documentledger --json doctor`, `documentledger --json status`, and `documentledger --json check` before committing. `finish` includes the link audit and configured validation when its advertised capability is available.

`doctor` and `link audit` are read-only. If audit reports a linked missing section, move its links to a current section or remove them with `documentledger link remove-section --doc DOC --section SECTION_ID --source-unit SOURCE_ID`; after the final obsolete link is removed, the orphan record is pruned. Unlinked structural churn is repaired by the next `scan`.

<!-- docledger-section: bootstrapping-a-new-repository -->

## Bootstrapping a new repository

For a new project, run `documentledger init`, create the first baseline with `documentledger --json scan`, and follow the dedicated [bootstrap workflow](bootstrap.md).

<!-- docledger-section: usage-limitations -->

## Limitations

Freshness is routed through explicit links and hash dimensions; an unlinked source change cannot identify a section. Git history replaces persisted historical scan files. The configured roots and extensions are intentionally static.

:::{deprecated} 0.6
`docledger`, the plural command groups, root `mark-fresh`, and legacy storage migration wrappers are compatibility-only. New automation must use `documentledger` and canonical singular command paths.
:::
