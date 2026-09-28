"""Sizes in bytes, and how a message names them."""

from __future__ import annotations

MIB = 1024 * 1024


def megabytes(size: int) -> str:
    """``size`` bytes in whole megabytes, for a message: ``25 MB``."""
    return f"{size // MIB} MB"
