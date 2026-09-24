"""Ids of this service's own records: a prefix for the kind, then random hex."""

from __future__ import annotations

import uuid


def new_id(prefix: str, length: int = 12) -> str:
    """For example ``acc_3f9a0c1b2d4e``."""
    return f"{prefix}_{uuid.uuid4().hex[:length]}"
