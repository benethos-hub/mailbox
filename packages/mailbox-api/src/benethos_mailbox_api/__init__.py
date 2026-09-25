"""Unified REST API for several mail providers and accounts."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("benethos-mailbox-api")
except PackageNotFoundError:  # pragma: no cover (running from a bare tree)
    __version__ = "0.0.0"

__all__ = ["__version__"]
