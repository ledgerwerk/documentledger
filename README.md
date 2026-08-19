[![PyPI - Version](https://img.shields.io/pypi/v/documentledger)](https://pypi.org/project/documentledger/)
![PyPI - Python Version](https://img.shields.io/pypi/pyversions/documentledger)

# Documentledger

Documentledger is a documentation freshness ledger for coding-agent workflows. It maps documentation sections to source units and reports affected documentation when linked implementation changes.

## Install

```bash
python -m pip install documentledger
documentledger --version
```

For development, install `python -m pip install -e ".[test,docs,dev]"`. Documentledger supports Python 3.10 through 3.13 and requires `ledgercore>=0.6.0,<0.7.0`.

## Quickstart

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

After updating and validating an affected section:

```bash
documentledger document mark-fresh --doc docs/usage.md --section usage-scan --reason "Updated after scan version VERSION."
```

## Canonical storage

The shared authority is `.ledger/ledger.toml` schema 3. Documentledger's tool config is `.ledger/documentledger/config.toml` version 2. Durable state is in the resolved `data` mount; rendered context and proposals use the resolved cache `artifacts` mount. Legacy root configs are migration inputs only.

## Workflow

1. Initialize the canonical project.
2. Scan to establish or update the deterministic baseline.
3. Inspect `document affected` and bounded `document build-context` output.
4. Link sections to source units with `link add-section` or review deterministic proposals.
5. Update affected documentation and run validation.
6. Mark updated sections fresh, audit links, and run `documentledger --json check`.

<!-- docledger-section: status -->

## Status

`documentledger --json status` reports initialization, storage bindings, latest scan counts, and the recommended next action.

<!-- docledger-section: commands -->

## Commands

Use `documentledger commands` or the [complete CLI reference](docs/cli.md) to inspect canonical command paths.

<!-- docledger-section: state-model -->

## State model

Documentledger persists deterministic hashes and integer versions in the canonical data mount. Rendered context and proposals are derived cache artifacts.

<!-- docledger-section: storage-migration -->

## Storage migration

Use `documentledger migrate status`, `migrate plan`, `migrate apply`, `migrate recover`, and `migrate cleanup` for explicit legacy migration.

## Bootstrapping a new repository

The first scan is a baseline; use `documentledger document build-context --bootstrap`, review deterministic link proposals and coverage (including intentional no-op mappings), then apply them before marking all configured documents fresh with `--allow-unlinked`.

## Documentation and development

The full Sphinx site is in [`docs/`](docs/index.md). Build it with:

```bash
python -m pip install -e ".[docs]"
python -m sphinx -W --keep-going -b html docs docs/_build/html
```

Run tests with `python -m pytest -q` and compile checks with `python -m compileall -q documentledger tests`.

## Compatibility

`docledger`, plural command groups, root `mark-fresh`, and legacy storage migration wrappers remain temporary compatibility interfaces. New automation must use `documentledger` and canonical singular command paths.

## License

Apache-2.0. See [`LICENSE`](LICENSE).
