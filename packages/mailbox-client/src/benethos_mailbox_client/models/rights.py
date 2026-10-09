"""Rights as users and roles hold them: grants on accounts, and the
rights of the service, by name (docs/PERMISSIONS.md)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Grant:
    """Rights on accounts: ``accounts`` ids or ``*`` for every one,
    ``allow`` groups such as ``mail.read`` or single operations. The rest
    narrows: whom it may send to, how many a day, which folders, until
    when. None: no narrowing."""

    accounts: tuple[str, ...]
    allow: tuple[str, ...]
    recipients: tuple[str, ...] | None = None
    max_sends_per_day: int | None = None
    folders: tuple[str, ...] | None = None
    expires_at: datetime | None = None
