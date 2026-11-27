# Bootstrapping a new repository

Bootstrap is the first documentation pass in a newly initialized project.

## Bootstrapping a new repository

Create the canonical project, establish a baseline, and build bounded context before adding or reviewing links.

<!-- docledger-section: why-the-first-scan-is-a-baseline -->

## First scan baseline

```bash
documentledger --json capabilities
documentledger init --project-name example
documentledger --json scan
```

The first scan hashes configured sources and docs but has no prior version for comparison. It therefore reports no deltas. Later scans can report affected sections and unlinked changed sources.

<!-- docledger-section: bootstrap-context -->

## Build bootstrap context

```bash
documentledger document build-context --bootstrap --out -
```

The output contains the current inventory and unlinked source evidence. Use it to decide what documentation should exist before adding links.

When `context_pagination.v1` is advertised, follow each `next_cursor` until `truncated` is false:

<!-- requires-capability: context_pagination.v1 -->

```bash
documentledger --json document build-context --bootstrap --page-size 40 --out -
documentledger --json document build-context --bootstrap --cursor NEXT_CURSOR --page-size 40 --out -
```

Without pagination support, narrow the requested scope and stop if relevant evidence remains omitted.

<!-- docledger-section: bootstrap-proposals -->

## Review deterministic proposals

```bash
documentledger --json link propose --all-docs --out-dir ./documentledger-maps
```

Inspect generated proposal files. When `proposal_manifest.v1` is advertised, also inspect the scan-bound manifest. Use manifest-owned imports only when both proposal capabilities are advertised.

<!-- requires-capability: proposal_manifest.v1, import_map_review.v1 -->

```bash
documentledger --json link import-map --directory ./documentledger-maps --review
documentledger --json link import-map --directory ./documentledger-maps --check-and-apply
```

If either capability is absent, do not use directory imports. Inspect the installed command help and use only supported file-based validation and apply options. Never bypass proposal review.

An empty top-level `sections: []` file is a valid reviewed no-op for a document. Empty `links: []` inside a named section remains invalid unless an explicit clearing operation is requested.

(setup-sequence)=

<!-- docledger-section: setup-sequence -->

## Coverage and final gates

```bash
documentledger --json link audit
documentledger --json coverage
```

Review coverage before freshness marking: every configured document must be linked or explicitly accepted as intentionally unlinked, while internal and test source units may remain intentionally omitted. Run configured tests, documentation validation, and the link audit. For a regular affected-document update, use `documentledger finish` after resolving mappings and recording any required no-change decisions. For this broad bootstrap-only transition, the explicit low-level `mark-fresh --all --allow-unlinked` command remains available:

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
