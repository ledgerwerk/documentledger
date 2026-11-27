# Quickstart

<!-- docledger-section: quickstart-canonical-path -->

## Canonical path

Check the installed command contract before using optional workflow features. Initialize a repository, establish a baseline, and inspect bootstrap context before adding mappings.

```bash
documentledger --json capabilities
documentledger init --project-name example
documentledger --json status
documentledger --json scan
documentledger document build-context --bootstrap --out -
```

If the context is truncated and `context_pagination.v1` is advertised, follow each `next_cursor` with another page request until `truncated` is false. If pagination is unavailable, narrow the requested documents or sections and stop if relevant evidence remains omitted.

<!-- requires-capability: context_pagination.v1 -->

```bash
documentledger --json document build-context --bootstrap --page-size 40 --out -
documentledger --json document build-context --bootstrap --cursor NEXT_CURSOR --page-size 40 --out -
```

Generate proposals only after reviewing the source and documentation context:

```bash
documentledger --json link propose --all-docs --out-dir ./documentledger-maps
```

When both `proposal_manifest.v1` and `import_map_review.v1` are advertised, inspect the scan-bound manifest and proposal files, review the owned batch, then apply it:

<!-- requires-capability: proposal_manifest.v1, import_map_review.v1 -->

```bash
documentledger --json link import-map --directory ./documentledger-maps --review
documentledger --json link import-map --directory ./documentledger-maps --check-and-apply
```

Do not use directory imports when either capability is absent. Inspect the installed `link import-map` help and use only its supported file-based validation and apply options. If proposals cannot be safely reviewed and applied, stop rather than bypassing review.

After applying reviewed mappings, audit links and inspect coverage:

```bash
documentledger --json link audit
documentledger --json coverage
```

The first scan creates a baseline and reports no source deltas. See [Bootstrap](bootstrap.md) for documentation and validation gates.

<!-- docledger-section: quickstart-incremental-path -->

## Incremental path

For normal source changes, review the affected documentation, update it from source evidence, and finish only through advertised capabilities.

```bash
documentledger --json capabilities
documentledger --json status
```

<!-- requires-capability: review.v1 -->

```bash
documentledger review
```

Update affected documentation and run configured validation. When `finish.v1` is advertised, finish audits links and runs validation before recording freshness. Use `--reviewed-no-change DOC#SECTION=REASON` only when the claim remains accurate, and use `--generated-verified DOC#SECTION=REASON` only after checking a generated reference.

<!-- requires-capability: finish.v1 -->

```bash
documentledger finish
documentledger --json status
documentledger --json check --complete
```

If finish is unavailable, require `validation.v1` before using manual freshness controls. Run validation and link audit, record only truthful scoped freshness dispositions, then run the strict completion check. If validation is unavailable, leave the work incomplete.

<!-- requires-capability: validation.v1 -->

```bash
documentledger document validate
documentledger --json link audit
documentledger document mark-fresh --doc PATH --section SECTION_ID --reason "Validated update."
documentledger --json check --complete
documentledger --json status
```
