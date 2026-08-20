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

An empty top-level `sections: []` file is a valid reviewed no-op for a document. Empty `links: []` inside a named section remains invalid unless an explicit clearing operation is requested.

<!-- docledger-section: setup-sequence -->

(setup-sequence)=

## Coverage and final gates

```bash
documentledger --json link audit
documentledger --json coverage
```

Review coverage before freshness marking: every configured document must be linked or explicitly accepted as intentionally unlinked, while internal and test source units may remain intentionally omitted. Run configured tests and documentation validation before freshness marking. For a reviewed bootstrap batch, finish with:

```bash
documentledger document mark-fresh --all --allow-unlinked \
  --reason "Bootstrap documentation completed after scan version VERSION."
```

Do not weaken lint, Sphinx, type-check, or documentation validation settings solely to make this gate pass.

Then run:

```bash
documentledger --json doctor
documentledger --json check
documentledger --json status
```

Mark fresh only after validation and only for intentionally linked or explicitly allowed unlinked docs.
