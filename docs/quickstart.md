# Quickstart

<!-- docledger-section: quickstart-canonical-path -->

## Canonical path

Probe capabilities before using optional workflow commands. To bootstrap a new repository, establish a baseline, create and review mappings, then inspect coverage:

```bash
documentledger init --project-name example
documentledger --json capabilities
documentledger --json status
documentledger --json scan
documentledger document build-context --bootstrap --out /tmp/documentledger-bootstrap.md
documentledger link propose --all-docs --out-dir /tmp/documentledger-maps
documentledger --json link import-map --directory /tmp/documentledger-maps --check-and-apply
documentledger --json link audit
documentledger --json coverage
```

The first scan creates a baseline and reports no source deltas. See [Bootstrap](bootstrap.md) for deliberate no-op mappings and validation gates.

<!-- docledger-section: quickstart-incremental-path -->

## Incremental path

For normal source changes, let `review` scan and summarize the work, edit affected docs, then finish through the configured gates:

```bash
documentledger --json capabilities
documentledger --json status
documentledger review
# edit affected documentation and run configured validation
documentledger finish
documentledger --json status
documentledger --json check
```

If an affected section is unchanged, record why with `--reviewed-no-change DOC#SECTION=REASON`; use `--generated-verified` for a checked generated reference. `finish` audits links and runs configured validation before writing freshness. For bootstrap and manual control, the lower-level scan, affected, build-context, link, and `document mark-fresh` commands remain available.
