"""Ids of this service's own records: a prefix for the kind, then 64 random
hex digits (256 bits) from the operating system's secure source."""

from __future__ import annotations

import secrets


def new_id(prefix: str) -> str:
    """For example ``acc_`` followed by 64 hex digits."""
    return f"{prefix}_{secrets.token_hex(32)}"
