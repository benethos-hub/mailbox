"""Pauses that double after each failure, up to a ceiling."""

from __future__ import annotations


def doubled(first: float, times: int, ceiling: float) -> float:
    """``first`` doubled ``times`` times, at most ``ceiling``. The
    exponent stops at 32, where any ceiling is reached, so a count
    that grew for weeks stays a number a float holds."""
    return float(min(ceiling, first * 2 ** min(max(times, 0), 32)))
