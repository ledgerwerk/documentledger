# Installation

Documentledger supports Python 3.10 through 3.13.

<!-- docledger-section: installation-package -->

## Install the package

```bash
python -m pip install documentledger
documentledger --version
documentledger --help
```

This page does not promise a particular published PyPI version. For a source checkout use:

```bash
python -m pip install -e ".[test,docs,dev]"
```

<!-- docledger-section: installation-documentation -->

## Install documentation dependencies

The docs extra and `docs/requirements.txt` contain the same four requirements: Sphinx, the Read the Docs theme, autodoc type hints, and MyST parser. The default build assumes they are already installed; it does not install packages or require network access.

<!-- docledger-section: installation-console-scripts -->

## Console scripts and completion

`documentledger` is the canonical console script. `docledger` remains a deprecated compatibility entry point and should not appear in new automation.

```bash
documentledger --install-completion
documentledger --show-completion
```

Use `python -m pip` with the interpreter that will run the command to avoid environment mismatches.
