from __future__ import annotations

try:
    from documentledger._version import version as __version__  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover
    __version__ = "0+unknown"
