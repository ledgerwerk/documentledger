from __future__ import annotations

import sys
import warnings

from documentledger.cli import run


def main() -> None:
    run()


def legacy_main() -> None:
    """Entry point for the deprecated 'docledger' executable."""
    warnings.warn(
        "'docledger' is deprecated; use 'documentledger' instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    print(
        "Warning: 'docledger' is deprecated. Use 'documentledger' instead.",
        file=sys.stderr,
    )
    run()
