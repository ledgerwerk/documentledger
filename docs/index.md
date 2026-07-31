# Documentledger

Documentledger is a documentation freshness ledger for coding-agent workflows. It records repository scans, maps documentation files to source units, reports stale documentation when linked implementation changes, and renders bounded update context for agents.

```{toctree}
:maxdepth: 2
:caption: Start here

installation
quickstart
concepts
```

```{toctree}
:maxdepth: 2
:caption: Workflows

usage
bootstrap
incremental-workflow
ci
migration
```

```{toctree}
:maxdepth: 2
:caption: Reference

configuration
cli
storage
schemas
errors
api/index
```

```{toctree}
:maxdepth: 2
:caption: Project

architecture
development
troubleshooting
changelog
```

<!-- docledger-section: documentation-freshness-workflow -->

## Documentation freshness workflow

The supported workflow is:

1. Run `documentledger --json status` to inspect the canonical workspace.
2. Run `documentledger --json scan` to compare current source and documentation hashes with the latest baseline.
3. Run `documentledger --json document affected` to find sections affected by linked source-unit changes.
4. Run `documentledger document build-context --affected --out /tmp/documentledger-context.md` to render bounded update context.
5. Inspect the affected sections and linked source evidence before editing.
6. Update the affected sections, run configured validation commands, then mark them fresh with `documentledger document mark-fresh --doc DOC --section SECTION --reason "Docs updated after scan version VERSION."`.

Documentledger stores durable state in the resolved `data` mount under `.ledger/documentledger/`. Do not edit canonical `.ledger/` records directly.
