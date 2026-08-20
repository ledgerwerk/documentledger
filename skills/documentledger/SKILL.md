---
name: documentledger
description: Maintain documentation freshness using the canonical documentledger CLI and linked source evidence.
---

# Documentledger workflow

Use this skill when updating documentation in a repository that uses Documentledger.

<!-- docledger-section: skill-entry -->

## Entry protocol

1. Run `documentledger --json status`.
2. Run `documentledger storage where` when storage layout is unclear.
3. Inspect `state`, `layout_source`, `recommended_command`, and reported `issues`.
4. Run `documentledger --json doctor`.
5. Stop on linked missing sections, missing source units, invalid roots, missing storage,
   schema errors, invalid bindings, or other link corruption. A later `scan` automatically
   prunes obsolete unlinked section records caused by generated-document heading churn.

<!-- docledger-section: skill-bootstrap -->

## Bootstrap branch

Use this when there is no baseline scan or usable documentation link graph.

1. Run `documentledger --json scan`.
2. Run `documentledger document build-context --bootstrap --out -` when the context should
   be piped directly to another process. Use `--out PATH` when a durable file is needed.
3. Inspect the saved context.
4. Run `documentledger link propose --all-docs --out-dir /tmp/documentledger-maps`.
5. Review and correct proposal files, including accepting top-level `sections: []` files as intentional no-op decisions.
6. Run `documentledger --json link import-map --directory /tmp/documentledger-maps --check-and-apply`.
7. Run `documentledger --json link audit` and `documentledger --json coverage`.
8. Review coverage: classify every configured document as linked or intentionally unlinked, and distinguish omitted/internal/test source units from unresolved coverage.
9. Run configured documentation validation commands.
10. Run `documentledger document mark-fresh --all --allow-unlinked --reason "Bootstrap documentation completed after scan version VERSION."` only after the coverage review explicitly accepts remaining unlinked docs.
11. Run `documentledger --json check` and `documentledger --json status`.

<!-- docledger-section: skill-incremental -->

## Incremental branch

1. Run `documentledger --json scan`.
2. Run `documentledger --json document affected`.
3. Run `documentledger document build-context --affected --out -` when the context should
   be streamed directly to an agent or another process. `--json` and raw Markdown streaming
   are separate modes; do not combine `--json` with `--out -` or `--print`.
4. Inspect affected sections and source-unit evidence.
5. Update only affected sections unless consistency requires more.
6. Run configured validation commands.
7. Mark the changed section fresh with a required reason.
8. Run `documentledger --json link audit` and `documentledger --json check`.
9. Finish with `documentledger --json status`.

During `scan`, current Markdown owns section existence and metadata. Harmless removed
unlinked entries are reconciled automatically; a removed linked section remains an actionable
orphan. Repair it by moving the edge to a current section with `link add-section`, or remove
the obsolete edge with `link remove-section --section SECTION_ID`, then rerun `link audit`.

<!-- docledger-section: skill-precision -->

## Precision and safety

Prefer `documentledger link add-section` edges over broad file links. Never invent edges just to improve coverage. Do not edit `.ledger/` records manually, add timestamps, or migrate storage as a side effect of documentation work. A first scan is a baseline and reports no deltas.

:::{deprecated}
`docledger`, plural groups, root `mark-fresh`, and legacy storage wrappers are compatibility-only. Use `documentledger` with canonical singular command paths in all new automation.
The legacy `docledger --json status` form is retained here only to identify the compatibility interface for migration.
The corresponding legacy forms are `docledger --json scan`, `docledger --json docs affected`, and `docledger docs build-context`.
The workflow contract remains: Inspect affected sections and linked changed source units first, then complete validation before `mark-fresh`.

Do not weaken lint, Sphinx, type-check, or documentation validation settings solely to make the completion gate pass. Fix documented content first; if a validation configuration change is necessary, report it separately with rationale.
:::
