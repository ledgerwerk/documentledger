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

Use the capability-aware workflow:

1. Run `documentledger --json capabilities` to discover advertised commands and features.
2. Run `documentledger --json status` to inspect workspace state and the recommended action.
3. Run `documentledger review` to scan current files and inspect affected documentation and relevant mapping candidates.
4. Resolve ambiguous mappings and edit the affected sections with the bounded context you need.
5. Run configured validation, then `documentledger finish`. Supply an explicit `--reviewed-no-change` or `--generated-verified` decision for affected sections whose text did not change.
6. Check `documentledger --json status` and `documentledger --json check` before committing.

`finish` audits links and runs configured validation before writing freshness. If capabilities do not advertise both `review.v1` and `finish.v1`, or for bootstrap and manual control, use the lower-level `scan`, `document affected`, `document build-context`, link commands, and `document mark-fresh`. Documentledger stores durable state in the resolved `data` mount under `.ledger/documentledger/`. Do not edit canonical `.ledger/` records directly.
