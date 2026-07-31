# Quickstart

<!-- docledger-section: quickstart-canonical-path -->

## Canonical path

```bash
documentledger init --project-name example
documentledger --json status
documentledger --json scan
documentledger document build-context --bootstrap --out /tmp/documentledger-bootstrap.md
documentledger link propose --all-docs --out-dir /tmp/documentledger-maps
documentledger --json link import-map --directory /tmp/documentledger-maps --check-and-apply
documentledger --json link audit
documentledger --json coverage
```

Review generated proposals before applying them. The first scan creates a baseline and therefore reports no deltas.

<!-- docledger-section: quickstart-incremental-path -->

## Incremental path

```bash
documentledger --json scan
documentledger --json document affected
documentledger document build-context --affected --out /tmp/documentledger-context.md
# edit and validate documentation
documentledger document mark-fresh \
  --doc docs/usage.md \
  --section usage-scan \
  --reason "Updated after scan version VERSION."
documentledger --json check
```

The section-level freshness operation updates the live affected projection and records the current tracked hashes.
