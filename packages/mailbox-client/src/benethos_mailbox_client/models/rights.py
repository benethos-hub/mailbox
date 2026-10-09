"""Rights as users and roles hold them: grants on accounts, the rights
of the service by name, and the catalogue that names them all
(docs/PERMISSIONS.md)."""

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


@dataclass(frozen=True)
class Permissions:
    """The catalogue of rights: each group and the operations it allows,
    and the groups of the service, named in a user's or a role's
    ``service``. The other groups are named in a grant's ``allow``."""

    groups: dict[str, tuple[str, ...]]
    service: tuple[str, ...]
