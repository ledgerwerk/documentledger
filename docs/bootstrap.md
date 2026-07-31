# Bootstrapping a new repository

Bootstrap is the first documentation pass in a newly initialized project.

## Bootstrapping a new repository

Create the canonical project, establish a baseline, and build bounded context before adding or reviewing links.

<!-- docledger-section: why-the-first-scan-is-a-baseline -->

## First scan baseline

```bash
documentledger init --project-name example
documentledger --json scan
```

The first scan hashes configured sources and docs but has no prior version for comparison. It therefore reports no deltas. Later scans can report affected sections and unlinked changed sources.

<!-- docledger-section: bootstrap-context -->

## Build bootstrap context

```bash
documentledger document build-context --bootstrap --out /tmp/documentledger-bootstrap.md
```

The output contains the current inventory and unlinked source evidence. Use it to decide what documentation should exist before adding links.

<!-- docledger-section: bootstrap-proposals -->

## Review deterministic proposals

```bash
documentledger link propose --all-docs --out-dir /tmp/documentledger-maps
documentledger --json link import-map --directory /tmp/documentledger-maps --validate
documentledger --json link import-map --directory /tmp/documentledger-maps --check-and-apply
```

`--validate` checks the complete batch without writing. Review and correct proposal files, then use `--check-and-apply` for an atomic application.

<!-- docledger-section: setup-sequence -->

## Coverage and final gates {#setup-sequence}

```bash
documentledger --json link audit
documentledger --json coverage
```

Run configured tests and documentation validation before freshness marking. Finish with:

```bash
documentledger --json doctor
documentledger --json check
documentledger --json status
```

Mark fresh only after validation and only for intentionally linked or explicitly allowed unlinked docs.
