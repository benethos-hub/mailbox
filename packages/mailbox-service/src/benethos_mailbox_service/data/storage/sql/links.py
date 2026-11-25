"""Links to an attachment in SQL."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa

from ....common.clock import iso, parse_iso
from ..links import StoredLink
from .rows import changed
from .schema import attachment_links

if TYPE_CHECKING:
    from .database import Database

_l = attachment_links.c


class SqlLinkRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def add(self, link: StoredLink) -> None:
        changed(
            self._db,
            sa.insert(attachment_links).values(
                id=link.id,
                secret_hash=link.secret_hash,
                account_id=link.account_id,
                message_id=link.message_id,
                attachment_id=link.attachment_id,
                token_id=link.token_id,
                expires_at=iso(link.expires_at),
                redeemed_at=iso(link.redeemed_at),
                redeemed_by=link.redeemed_by,
            ),
        )

    def find(self, secret_hash: str) -> StoredLink | None:
        with self._db.connected() as conn:
            row = (
                conn.execute(
                    sa.select(attachment_links).where(_l.secret_hash == secret_hash)
                )
                .mappings()
                .first()
            )
        return None if row is None else _link(row)

    def redeem(self, link_id: str, at: datetime, by: str) -> bool:
        return bool(
            changed(
                self._db,
                sa.update(attachment_links)
                .where(
                    _l.id == link_id,
                    _l.redeemed_at.is_(None),
                    _l.expires_at > iso(at),
                )
                .values(redeemed_at=iso(at), redeemed_by=by),
            )
        )

    def release(self, link_id: str) -> None:
        changed(
            self._db,
            sa.update(attachment_links)
            .where(_l.id == link_id)
            .values(redeemed_at=None, redeemed_by=None),
        )

    def purge(self, now: datetime) -> int:
        removed = changed(
            self._db,
            sa.delete(attachment_links).where(
                sa.or_(_l.redeemed_at.is_not(None), _l.expires_at <= iso(now))
            ),
        )
        if removed:
            self._db.shrink()
        return removed


def _link(row: sa.RowMapping) -> StoredLink:
    return StoredLink(
        id=row["id"],
        secret_hash=row["secret_hash"],
        account_id=row["account_id"],
        message_id=row["message_id"],
        attachment_id=row["attachment_id"],
        token_id=row["token_id"],
        expires_at=parse_iso(row["expires_at"]),
        redeemed_at=parse_iso(row["redeemed_at"]),
        redeemed_by=row["redeemed_by"],
    )
