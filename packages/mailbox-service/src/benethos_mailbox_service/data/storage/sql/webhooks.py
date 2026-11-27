"""Webhooks in SQL. The secret stays encrypted, as the vault sealed it."""

from __future__ import annotations

import builtins
import json
from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa

from benethos_mailbox_common.storage import rows as table_rows

from ....common.clock import iso, parse_iso
from ...models import ChangeKind, Webhook
from ..webhooks import Attempt, Delivery, Sealed, WebhookRecord
from .schema import webhook_attempts, webhooks

if TYPE_CHECKING:
    from .database import Database

_w = webhooks.c
_a = webhook_attempts.c


class SqlWebhookRepository:
    def __init__(self, db: Database) -> None:
        self._db = db
        self._rows = table_rows.SqlRows(
            db, webhooks, "webhook", _webhook, order=[_w.created_at, _w.id]
        )

    def add(self, record: WebhookRecord) -> None:
        hook, secret, delivery = record.webhook, record.secret, record.delivery
        table_rows.rows_changed(
            self._db,
            sa.insert(webhooks).values(
                id=hook.id,
                user_id=hook.user_id,
                url=hook.url,
                events=json.dumps(hook.events),
                accounts=_accounts(hook.accounts),
                created_at=iso(hook.created_at),
                key_id=secret.key_id,
                nonce=secret.nonce,
                ciphertext=secret.ciphertext,
                cursor=delivery.cursor,
                attempts=delivery.attempts,
                next_attempt_at=iso(delivery.next_attempt_at),
                last_delivery_at=iso(hook.last_delivery_at),
                last_error=hook.last_error,
            ),
        )

    def get(self, webhook_id: str) -> WebhookRecord:
        return self._rows.get(webhook_id)

    def list(self) -> list[WebhookRecord]:
        return self._rows.list()

    def delete(self, webhook_id: str) -> None:
        self._rows.delete(webhook_id)

    def change(
        self,
        webhook_id: str,
        *,
        url: str,
        events: builtins.list[ChangeKind],
        accounts: builtins.list[str] | None,
    ) -> None:
        table_rows.rows_changed(
            self._db,
            sa.update(webhooks)
            .where(_w.id == webhook_id)
            .values(url=url, events=json.dumps(events), accounts=_accounts(accounts)),
        )

    def set_secret(self, webhook_id: str, secret: Sealed) -> None:
        table_rows.rows_changed(
            self._db,
            sa.update(webhooks)
            .where(_w.id == webhook_id)
            .values(
                key_id=secret.key_id, nonce=secret.nonce, ciphertext=secret.ciphertext
            ),
        )

    def delete_for_user(self, user_id: str) -> int:
        return table_rows.rows_changed(
            self._db, sa.delete(webhooks).where(_w.user_id == user_id)
        )

    def update(
        self,
        webhook_id: str,
        delivery: Delivery,
        *,
        last_delivery_at: datetime | None,
        last_error: str | None,
    ) -> None:
        table_rows.rows_changed(
            self._db,
            sa.update(webhooks)
            .where(_w.id == webhook_id)
            .values(
                cursor=delivery.cursor,
                attempts=delivery.attempts,
                next_attempt_at=iso(delivery.next_attempt_at),
                last_delivery_at=iso(last_delivery_at),
                last_error=last_error,
            ),
        )

    def add_attempt(self, attempt: Attempt, *, keep: int) -> None:
        """Check the webhook, add the attempt and keep the last ``keep``,
        in one transaction."""
        with self._db.connected() as conn:
            there = conn.execute(
                sa.select(_w.id).where(_w.id == attempt.webhook_id)
            ).first()
            if there is None:
                return
            conn.execute(
                sa.insert(webhook_attempts).values(
                    webhook_id=attempt.webhook_id,
                    delivery_id=attempt.delivery_id,
                    at=iso(attempt.at),
                    events=attempt.events,
                    status=attempt.status,
                    error=attempt.error,
                )
            )
            kept = (
                sa.select(_a.seq)
                .where(_a.webhook_id == attempt.webhook_id)
                .order_by(_a.seq.desc())
                .limit(keep)
            )
            conn.execute(
                sa.delete(webhook_attempts).where(
                    _a.webhook_id == attempt.webhook_id, _a.seq.not_in(kept)
                )
            )

    def attempts(self, webhook_id: str) -> builtins.list[Attempt]:
        with self._db.connected() as conn:
            rows = conn.execute(
                sa.select(webhook_attempts)
                .where(_a.webhook_id == webhook_id)
                .order_by(_a.seq.desc())
            ).mappings()
            return [
                Attempt(
                    webhook_id=row["webhook_id"],
                    delivery_id=row["delivery_id"],
                    at=parse_iso(row["at"]),
                    events=row["events"],
                    status=row["status"],
                    error=row["error"],
                )
                for row in rows
            ]


def _accounts(accounts: builtins.list[str] | None) -> str | None:
    return json.dumps(accounts) if accounts is not None else None


def _webhook(row: sa.RowMapping) -> WebhookRecord:
    accounts = row["accounts"]
    return WebhookRecord(
        webhook=Webhook(
            id=row["id"],
            url=row["url"],
            events=json.loads(row["events"]),
            accounts=json.loads(accounts) if accounts is not None else None,
            user_id=row["user_id"],
            created_at=parse_iso(row["created_at"]),
            last_delivery_at=parse_iso(row["last_delivery_at"]),
            last_error=row["last_error"],
        ),
        secret=Sealed(row["key_id"], row["nonce"], row["ciphertext"]),
        delivery=Delivery(
            cursor=row["cursor"],
            attempts=row["attempts"],
            next_attempt_at=parse_iso(row["next_attempt_at"]),
        ),
    )
