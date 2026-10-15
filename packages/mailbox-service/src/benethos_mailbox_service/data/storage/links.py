"""Links to an attachment: a secret that hands out one attachment once,
kept as its digest.

It only stores. The domain makes the secret, decides who may share and
whether a link still holds.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Protocol

from .table import drop_where


@dataclass(frozen=True, slots=True)
class StoredLink:
    """A link: the digest of its secret, the attachment it hands out, the
    API token that made it, when it ends, and when and by which client
    address it was used."""

    id: str
    secret_hash: str
    account_id: str
    message_id: str
    attachment_id: str
    token_id: str
    expires_at: datetime
    redeemed_at: datetime | None = None
    redeemed_by: str | None = None


class LinkRepository(Protocol):
    def add(self, link: StoredLink) -> None: ...

    def find(self, secret_hash: str) -> StoredLink | None:
        """The link whose secret has this digest."""
        ...

    def redeem(self, link_id: str, at: datetime, by: str) -> bool:
        """Mark the link used at ``at`` by the client address ``by``. False
        when it was used already or ended by ``at``: of two at once, one
        wins."""
        ...

    def purge(self, now: datetime) -> int:
        """Remove every link used or ended by ``now``: how many."""
        ...


class InMemoryLinkRepository:
    def __init__(self) -> None:
        self._links: dict[str, StoredLink] = {}

    def add(self, link: StoredLink) -> None:
        self._links[link.id] = link

    def find(self, secret_hash: str) -> StoredLink | None:
        return next(
            (link for link in self._links.values() if link.secret_hash == secret_hash),
            None,
        )

    def redeem(self, link_id: str, at: datetime, by: str) -> bool:
        link = self._links.get(link_id)
        if link is None or link.redeemed_at is not None or link.expires_at <= at:
            return False
        self._links[link_id] = replace(link, redeemed_at=at, redeemed_by=by)
        return True

    def purge(self, now: datetime) -> int:
        return drop_where(
            self._links,
            lambda _, link: link.redeemed_at is not None or link.expires_at <= now,
        )
