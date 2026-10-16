"""Links to an attachment in SQLite."""

from __future__ import annotations

import sqlite3
from datetime import datetime

from ....common.clock import iso, parse_iso
from ..links import StoredLink
from .database import Database


class SqliteLinkRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def add(self, link: StoredLink) -> None:
        self._db.execute(
            "INSERT INTO attachment_links (id, secret_hash, account_id,"
            " message_id, attachment_id, token_id, expires_at, redeemed_at,"
            " redeemed_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                link.id,
                link.secret_hash,
                link.account_id,
                link.message_id,
                link.attachment_id,
                link.token_id,
                iso(link.expires_at),
                iso(link.redeemed_at),
                link.redeemed_by,
            ),
        )

    def find(self, secret_hash: str) -> StoredLink | None:
        return self._db.one_as(
            _link,
            "SELECT * FROM attachment_links WHERE secret_hash = ?",
            (secret_hash,),
        )

    def redeem(self, link_id: str, at: datetime, by: str) -> bool:
        return bool(
            self._db.execute(
                "UPDATE attachment_links SET redeemed_at = ?, redeemed_by = ?"
                " WHERE id = ? AND redeemed_at IS NULL AND expires_at > ?",
                (iso(at), by, link_id, iso(at)),
            )
        )

    def release(self, link_id: str) -> None:
        self._db.execute(
            "UPDATE attachment_links SET redeemed_at = NULL, redeemed_by = NULL"
            " WHERE id = ?",
            (link_id,),
        )

    def purge(self, now: datetime) -> int:
        removed = self._db.execute(
            "DELETE FROM attachment_links"
            " WHERE redeemed_at IS NOT NULL OR expires_at <= ?",
            (iso(now),),
        )
        if removed:
            self._db.shrink()
        return removed


def _link(row: sqlite3.Row) -> StoredLink:
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
