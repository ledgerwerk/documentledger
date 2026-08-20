# Incremental workflow

This is the normal agent operation after bootstrap.

<!-- docledger-section: incremental-sequence -->

## Sequence

1. `documentledger --json status`
2. `documentledger --json doctor`
3. `documentledger --json scan`
4. `documentledger --json document affected`
5. `documentledger document build-context --affected --out -`
6. Inspect source-unit evidence and section links.
7. Edit affected sections unless consistency requires a broader update.
8. Run configured validation commands.
9. Mark updated sections fresh.
10. Run `documentledger --json link audit`.
11. Run `documentledger --json check`.
12. Finish with `documentledger --json status`.

`scan` reconciles each existing durable document record with the current Markdown section
index before deciding that the scan is unchanged. It adds new headings, refreshes structural
metadata for surviving sections, prunes removed sections with empty `links`, and retains
removed linked sections as actionable orphans. The reconciliation counters are included in
the scan result. `doctor` and `link audit` remain read-only.

<!-- docledger-section: incremental-freshness-projection -->

## Live freshness projection

Section-level `documentledger document mark-fresh` updates affectedness from the current scan without another scan. It refreshes section hashes and the tracked source-unit hash set at the latest scan version. A reason is required so the state transition remains reviewable.

<!-- docledger-section: incremental-scope -->

## Scope discipline

Use the rendered context and source-unit ids to keep edits bounded. Update linked sections when their tracked dimensions changed, link newly documented source units deliberately, and leave unrelated docs alone. Never invent links solely to improve a coverage percentage.
