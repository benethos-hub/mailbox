"""The changes of the accounts since a state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Change:
    """One change of the change feed: ids only."""

    type: str  # e.g. "message.created"
    id: str
    account_id: str
    at: datetime


@dataclass(frozen=True, slots=True)
class Changes:
    """Changes after a point in the change feed, oldest first."""

    changes: list[Change]
    state: str
    more: bool
