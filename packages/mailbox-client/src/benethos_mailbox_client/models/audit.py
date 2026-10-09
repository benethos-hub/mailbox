"""The audit of administration: who did what to which record, and how
it came out (docs/AUDIT.md)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Activity:
    """One activity of the audit. ``activity`` names it, e.g.
    ``users.token_revoked``, ``record`` is the id of what it touched,
    ``credential`` how the user came (a token's name, ``password``),
    ``outcome`` e.g. ``done`` or ``refused``, ``detail`` the sentence of
    the log."""

    id: str
    at: datetime
    activity: str
    user_id: str | None
    user_name: str
    credential: str | None
    record: str | None
    source: str | None
    outcome: str
    detail: str
