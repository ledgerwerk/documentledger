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

Initialize the project and inspect the capability contract before selecting a workflow:

```bash
documentledger init --project-name example
documentledger --json capabilities
documentledger --json status
```

For incremental documentation updates, use the capability-aware review and finish path:

```bash
documentledger review
# edit the affected documentation sections
documentledger finish
documentledger --json status
```

`review` scans current files, reports affected sections and relevant mapping work, and applies only safe exact mappings. `finish` audits links, runs configured validation commands, and records freshness only when all gates pass. For an unchanged section, provide a reason with `--reviewed-no-change DOC#SECTION=REASON`; use `--generated-verified DOC#SECTION=REASON` for verified generated references.

## Canonical storage

The shared authority is `.ledger/ledger.toml` schema 3. Documentledger's tool config is `.ledger/documentledger/config.toml` version 2. Durable state is in the resolved `data` mount; rendered context and proposals use the resolved cache `artifacts` mount. Legacy root configs are migration inputs only.

## Workflow

1. Initialize the canonical project and inspect `documentledger --json capabilities`.
2. Use `documentledger review` for incremental changes. It scans, summarizes affected sections and relevant unmapped production changes, and links only deterministic exact candidates.
3. Inspect `documentledger review --details` or bounded `documentledger document build-context --affected` when more evidence is needed. Resolve ambiguous mappings deliberately.
4. Edit affected documentation and run the configured validation commands.
5. Run `documentledger finish`, supplying an explicit no-change or generated-reference decision when needed. It writes freshness only after mapping review, link audit, and configured validation succeed.
6. Inspect `documentledger --json status` and `documentledger --json check`.

For bootstrapping or manual control, the lower-level `scan`, `document affected`, `document build-context`, `link propose`/`link import-map`, `link audit`, and `document mark-fresh` commands remain available. `document mark-fresh` is the explicit low-level freshness operation; use it only after reviewing mappings and completing validation.

<!-- docledger-section: status -->

## Status

`documentledger --json status` reports workspace initialization, storage bindings, scan counts, mapping/freshness state, and a recommended next action. The top-level `state` distinguishes `bootstrap_required`, `mapping_incomplete`, `incremental_affected`, and `incremental_clean`. The `freshness_state` is `affected` or `clean`; `mapping_state` is `bootstrap_required`, `review_required`, or `complete`. Test, private, and generated changes are excluded from mapping review by default unless `mapping_review_roles` opts them in.

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

The first scan is a baseline. For bootstrap, use `documentledger document build-context --bootstrap`, review deterministic proposals and coverage (including intentional no-op mappings), then apply them. `document mark-fresh --all --allow-unlinked` remains an explicit low-level bootstrap operation when its broader scope is intentional; the normal incremental path uses `review` and `finish`.

## Documentation and development

The full Sphinx site is in [`docs/`](docs/index.md). Build it with:

```bash
python -m pip install -e ".[docs]"
python -m sphinx -W --keep-going -b html docs docs/_build/html
```

Run tests with `python -m pytest -q` and compile checks with `python -m compileall -q documentledger tests`.

## Compatibility

`docledger`, plural command groups, root `mark-fresh`, and legacy storage migration wrappers remain compatibility interfaces. New automation should probe `documentledger --json capabilities` and use canonical singular command paths. `document mark-fresh` remains available for explicit low-level workflows; prefer `review` and `finish` when their capabilities are advertised.

## License

Apache-2.0. See [`LICENSE`](LICENSE).
