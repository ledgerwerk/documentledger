# Incremental workflow

This is the normal agent operation after bootstrap.

<!-- docledger-section: incremental-sequence -->

## Sequence

1. `documentledger --json capabilities`
2. `documentledger --json status` and `documentledger --json doctor`
3. `documentledger review` to scan, summarize affected sections, and inspect relevant mapping candidates.
4. Resolve ambiguous mappings and render bounded context with `documentledger document build-context --affected --out -` when needed.
5. Edit affected sections and run configured validation commands.
6. Run `documentledger finish`, supplying `--reviewed-no-change` or `--generated-verified` decisions for unchanged affected sections.
7. Inspect `documentledger --json status`, `documentledger --json link audit`, and `documentledger --json check`.

The capability contract is the source of truth for optional workflow commands. The lower-level `scan`, `document affected`, `link propose`/`link import-map`, and `document mark-fresh` commands remain available for bootstrap and manual control.
`scan` reconciles each existing durable document record with the current Markdown section
index before deciding that the scan is unchanged. It adds new headings, refreshes structural
metadata for surviving sections, prunes removed sections with empty `links`, and retains
removed linked sections as actionable orphans. The reconciliation counters are included in
the scan result. `doctor` and `link audit` remain read-only.

<!-- docledger-section: incremental-freshness-projection -->

## Live freshness projection

`documentledger finish` is the normal freshness gate: it requires resolved mappings, a passing link audit, and successful configured validation before recording section dispositions. Changed sections are recorded as `updated`; unchanged affected sections need a `reviewed-no-change` or `generated-verified` decision. The lower-level section-specific `documentledger document mark-fresh` remains available for manual workflows and updates the live affected projection without another scan.

<!-- docledger-section: incremental-scope -->

## Scope discipline

Use the rendered context and source-unit ids to keep edits bounded. Update linked sections when their tracked dimensions changed, link newly documented source units deliberately, and leave unrelated docs alone. Never invent links solely to improve a coverage percentage.
