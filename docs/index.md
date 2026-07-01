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

## Documentation freshness workflow

The supported workflow is:

1. Run `docledger --json status` to confirm that the workspace is initialized.
2. Run `docledger --json scan` to record the current source and documentation hashes.
3. Run `docledger --json docs stale` to find documentation whose linked sources changed.
4. Run `docledger docs build-context --all --print` to render update context for stale docs and unlinked changed sources.
5. Inspect the linked source files before editing stale documentation.
6. Update the stale documentation, run configured validation commands, then mark updated docs fresh with `docledger mark-fresh --doc DOC --reason "Docs updated after scan SCAN_ID."`.

Documentledger stores its own state under the configured `.documentledger/` directory. Do not edit that directory directly.
