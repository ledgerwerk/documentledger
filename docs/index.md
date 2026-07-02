# Documentledger

Documentledger is a documentation freshness ledger for coding-agent workflows. It records repository scans, maps documentation files to source files, reports stale documentation when linked source files change or disappear, and renders update context for agents.

```{toctree}
:maxdepth: 2

usage
architecture
api
bootstrap
troubleshooting
```

<!-- docledger-section: index-documentation-freshness-workflow -->

## Documentation freshness workflow

The supported workflow is:

1. Run `docledger --json status` to confirm that the workspace is initialized.
2. Run `docledger --json scan` to rewrite `.documentledger/scan.yaml` when current source hashes, documentation hashes, source-unit inventory, or changed source units differ from the latest baseline.
3. Run `docledger --json docs affected` to find the documentation sections whose linked source units changed.
4. Run `docledger docs build-context --affected --print` to render update context for affected sections and unlinked changed sources.
5. Inspect the affected sections and linked changed source units before editing documentation.
6. Update only the affected sections by default, run configured validation commands, then mark the updated section or doc fresh with `docledger mark-fresh --doc DOC --section SECTION --reason "Docs updated after scan version VERSION."`.

Documentledger stores its own state under the configured `.documentledger/` directory. Do not edit that directory directly.
