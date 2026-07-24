# Troubleshooting

## `status` reports `uninitialized`

An `uninitialized` result can mean there is no config yet, or that `documentledger.toml` exists but `.documentledger/storage.yaml` is missing. This happens when the storage directory was removed or never created. Re-run initialization from the project root:

```bash
docledger init
```

`init` refuses to run when a config already exists; remove the stale config first only if you intend to start over.

## `scan` fails with `storage_missing`

A command that requires an initialized workspace raises `storage_missing` when the config exists but storage metadata is absent. Resolve it the same way as the missing-storage `uninitialized` case: run `docledger init`.

## `mark-fresh` fails with `unlinked_doc`

`mark-fresh` rejects documents that have no linked sources by default, because an unlinked document can never become stale from source changes and would silently drift. Either add links first:

```bash
docledger links add --doc docs/index.md --source documentledger/cli.py --reason "Navigation page maps to the CLI."
```

or explicitly record the document as intentionally unlinked:

```bash
docledger mark-fresh --doc docs/index.md --allow-unlinked --reason "Navigation page; intentionally unlinked."
```

## Every change makes too many docs stale

If a small source change marks many docs stale, the link graph is too broad. Each document should be linked only to the source files it actually describes. Narrow the links:

```bash
docledger links remove --doc docs/usage.md --source documentledger/models.py
```

Broad links (for example linking every doc to every module) defeat the selective-update model. Keep links precise.

## A changed source is reported as unlinked

`unlinked_changed_sources` lists source files that changed since the last scan but have no doc record link. Decide for each one whether it needs documentation, then either add a link or leave it untracked. Use the bootstrap flag to surface all unlinked sources, not just changed ones:

```bash
docledger docs build-context --bootstrap --out /tmp/docledger-bootstrap.md
```

## The Sphinx build warns about files inside the virtual environment

The documentation build creates a virtual environment under `docs/venv/`. `docs/conf.py` excludes `_build`, `venv`, and `.documentledger` from the Sphinx source scan. If you still see warnings from virtual-environment files, confirm `exclude_patterns` in `docs/conf.py` includes `venv` and `venv/**`, and remove any stale `docs/venv/` before rebuilding:

```bash
rm -rf docs/venv docs/_build
bash docs/build.sh
```

## `sphinx-build` is not found

`docs/build.sh` creates and activates `docs/venv/` and installs `docs/requirements.txt`, which provides `sphinx-build`. If the build cannot find `sphinx-build`, ensure the script reaches the `source "$VENV_DIR/bin/activate"` step and that `docs/requirements.txt` installs successfully (it requires network access on first run).

## Storage migration errors

- `storage_migration_required`: run `docledger storage migrate --dry-run` and review the plan.
- `project_uuid_mismatch`: compare the legacy and shared manifest identities; pass `--adopt-project-uuid` only after review.
- `source_index_missing` or `source_index_repair_failed`: restore the committed `source-index.json`, or use explicit repair only when the reconstructed SHA-256 exactly matches `scan.yaml`.
- `storage_binding_invalid`: repair the canonical binding through an explicit initialization/recovery command; status and verification never repair it silently.
- `legacy_cleanup_unsafe`: verify the completed migration journal, unchanged legacy inventory, and provisional proposal disposition before using `--yes`.
