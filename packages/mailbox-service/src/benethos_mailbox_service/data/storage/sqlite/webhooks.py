"""Webhooks in SQLite. The secret stays encrypted, as the vault sealed it."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from ...models.webhooks import Webhook
from ..table import missing
from ..webhooks import Delivery, Sealed, WebhookRecord
from .database import Database, iso, parse_iso


class SqliteWebhookRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def add(self, record: WebhookRecord) -> None:
        hook, secret, delivery = record.webhook, record.secret, record.delivery
        self._db.execute(
            "INSERT INTO webhooks (id, user_id, url, events, accounts, created_at,"
            " key_id, nonce, ciphertext, cursor, attempts, next_attempt_at,"
            " last_delivery_at, last_error)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                hook.id,
                hook.user_id,
                hook.url,
                json.dumps(hook.events),
                json.dumps(hook.accounts) if hook.accounts is not None else None,
                iso(hook.created_at),
                secret.key_id,
                secret.nonce,
                secret.ciphertext,
                delivery.cursor,
                delivery.attempts,
                _time(delivery.next_attempt_at),
                _time(hook.last_delivery_at),
                hook.last_error,
            ),
        )

    def get(self, webhook_id: str) -> WebhookRecord:
        row = self._db.one("SELECT * FROM webhooks WHERE id = ?", (webhook_id,))
        if row is None:
            raise missing("webhook", webhook_id)
        return _record(row)

    def list(self) -> list[WebhookRecord]:
        rows = self._db.query("SELECT * FROM webhooks ORDER BY created_at, id")
        return [_record(row) for row in rows]

    def delete(self, webhook_id: str) -> None:
        self._db.must_change(
            "DELETE FROM webhooks WHERE id = ?", (webhook_id,), "webhook", webhook_id
        )

    def update(
        self,
        webhook_id: str,
        delivery: Delivery,
        *,
        last_delivery_at: datetime | None,
        last_error: str | None,
    ) -> None:
        self._db.execute(
            "UPDATE webhooks SET cursor = ?, attempts = ?, next_attempt_at = ?,"
            " last_delivery_at = ?, last_error = ? WHERE id = ?",
            (
                delivery.cursor,
                delivery.attempts,
                _time(delivery.next_attempt_at),
                _time(last_delivery_at),
                last_error,
                webhook_id,
            ),
        )


def _time(value: datetime | None) -> str | None:
    return iso(value) if value is not None else None


def _record(row: sqlite3.Row) -> WebhookRecord:
    accounts = row["accounts"]
    return WebhookRecord(
        webhook=Webhook(
            id=row["id"],
            url=row["url"],
            events=json.loads(row["events"]),
            accounts=json.loads(accounts) if accounts is not None else None,
            user_id=row["user_id"],
            created_at=parse_iso(row["created_at"]),
            last_delivery_at=(
                parse_iso(row["last_delivery_at"]) if row["last_delivery_at"] else None
            ),
            last_error=row["last_error"],
        ),
        secret=Sealed(row["key_id"], row["nonce"], row["ciphertext"]),
        delivery=Delivery(
            cursor=row["cursor"],
            attempts=row["attempts"],
            next_attempt_at=(
                parse_iso(row["next_attempt_at"]) if row["next_attempt_at"] else None
            ),
        ),
    )
