# Troubleshooting

Use JSON output when an automated workflow needs stable error codes and remediation details.

<!-- docledger-section: troubleshooting-executable -->

## The executable is not found

Install the package into the active environment with `python -m pip install -e .`, then verify `documentledger --version`. In a source checkout, prefer `python -m pip` so the installer matches the selected interpreter.

<!-- docledger-section: troubleshooting-deprecation -->

## A deprecation warning appears

The `docledger` executable and plural/legacy command paths are compatibility wrappers. Replace them with `documentledger`, `document`, `source`, `link`, and the `migrate` command group.

<!-- docledger-section: troubleshooting-binding -->

## Canonical storage binding is invalid

Run `documentledger storage where`, `documentledger storage validate --strict`, and `documentledger --json doctor`. Read-only commands do not repair bindings. Review the shared schema-3 manifest and its `data` project and `artifacts` cache mounts before applying an explicit migration or repair.

<!-- docledger-section: troubleshooting-config -->

## Configuration validation fails

Inspect the effective config with `documentledger config show` and validate it with `documentledger config validate`. The canonical tool file is `.ledger/documentledger/config.toml`, version 2. Unknown fields, wrong types, unsupported extensions, or a missing version require a config edit or explicit migration.

<!-- docledger-section: troubleshooting-baseline -->

## There is no baseline or no links

Run `documentledger --json scan` once to create a baseline. A clean first scan is expected. Then use `documentledger document build-context --bootstrap`, review `link propose` output, apply reviewed maps, and audit links.

<!-- docledger-section: troubleshooting-stale -->

## Check reports stale sections

Run `documentledger document affected`, inspect bounded context, update the affected sections, run validation, and use section-level `documentledger document mark-fresh`. Do not mark fresh before validation.

<!-- docledger-section: troubleshooting-index -->

## Source index is missing or corrupt

Run `documentledger --json doctor` and `documentledger source list`. The source index is deterministic committed baseline state; repair is allowed only when exact reconstruction matches the recorded hash. Do not delete it or hand-edit it.

<!-- docledger-section: troubleshooting-selectors -->

## Cursor or selector errors occur

Use a cursor returned by the immediately preceding paginated `source list` call. `document build-context` requires exactly one of `--affected`, `--doc`, `--all`, or `--bootstrap`; `--section` requires `--doc`.

<!-- docledger-section: troubleshooting-maps -->

## Mapping batch validation fails

Run `link import-map` in validate-only mode, correct every invalid doc path, section id, source unit, coverage, impact, or duplicate edge, and rerun before check-and-apply.

<!-- docledger-section: troubleshooting-migration -->

## Migration conflicts or is interrupted

Regenerate and review `documentledger migrate plan storage-layout --output migration.json`. Apply only a matching digest with `documentledger migrate apply storage-layout --plan-file migration.json`. For an interrupted operation, use `documentledger migrate recover --journal JOURNAL --policy auto`, then inspect status before cleanup.

<!-- docledger-section: troubleshooting-sphinx -->

## Sphinx fails with warnings or autodoc import errors

Install the package and exact docs extra, then run `python -m sphinx -W --keep-going -b html docs docs/_build/html`. Fix unresolved references, malformed MyST, duplicate labels, or import errors; do not silence broad warning classes. API targets must import in the docs environment.

<!-- docledger-section: status-reports-uninitialized -->

## Status reports uninitialized

Run `documentledger storage where`, then `documentledger init` when no canonical project can be resolved.

<!-- docledger-section: scan-fails-with-storage-missing -->

## Scan fails with storage missing

Inspect `documentledger --json doctor` and repair or migrate canonical bindings explicitly before scanning.

<!-- docledger-section: a-changed-source-is-reported-as-unlinked -->

## A changed source is reported as unlinked

Review source-unit evidence and add a deliberate section-level link; do not create an edge solely to remove the warning.

<!-- docledger-section: every-change-makes-too-many-docs-stale -->

## Every change makes too many docs stale

Replace broad file links with precise section-to-source-unit links and choose the appropriate tracked hash coverage.

<!-- docledger-section: mark-fresh-fails-with-unlinked-doc -->

## Mark fresh fails with unlinked doc

Add a real link or use `--allow-unlinked` only when the document is intentionally unlinked.

<!-- docledger-section: sphinx-build-is-not-found -->

## Sphinx build is not found

Install `python -m pip install -e ".[docs]"` in the active environment and invoke `python -m sphinx`.

<!-- docledger-section: the-sphinx-build-warns-about-files-inside-the-virtual-environment -->

## The Sphinx build warns about files inside the virtual environment

The configuration excludes `docs/venv` and `docs/_build`; use the strict build from the repository root.

<!-- docledger-section: storage-migration-errors -->

## Storage migration errors

Regenerate a migration plan, verify its digest, and use the journal recovery policy before attempting cleanup.
