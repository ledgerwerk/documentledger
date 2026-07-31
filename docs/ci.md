# Continuous integration

<!-- docledger-section: ci-gate -->

## Deterministic gate

Run the following from the repository root:

```bash
documentledger --json check
python -m pytest -q
python -m compileall -q documentledger tests
python -m sphinx -W --keep-going -b html docs docs/_build/html
```

`check` returns non-zero for stale documentation, invalid storage schema or bindings, source-index integrity failures, invalid links, and configured validation failures. The Sphinx build treats warnings as errors and keeps going long enough to report the complete warning set.

<!-- docledger-section: ci-environment -->

## CI environment

Run the strict docs build in an Ubuntu/Python 3.13 job with `python -m pip install -e ".[docs]"`. Keep the normal unit-test matrix across the supported operating systems and Python versions. CLI reference generation is checked with `python scripts/generate_cli_reference.py --check`.

<!-- docledger-section: ci-network-policy -->

## Network policy

The HTML build is local and does not use intersphinx or download dependencies. Run external link checking separately or make it non-blocking when network reliability is outside the repository's control; internal references and Sphinx warnings remain blocking.
