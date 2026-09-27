"""Webhooks and where each one's delivery stands. The repository only
stores. The domain decides what is posted, and when."""

from __future__ import annotations

import builtins
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Protocol

from ..models.webhooks import Webhook
from .table import missing


@dataclass(frozen=True)
class Sealed:
    """A secret encrypted with the data key."""

    key_id: str
    nonce: bytes
    ciphertext: bytes


@dataclass(frozen=True)
class Delivery:
    """Where a webhook's delivery stands: the point in the event log it
    has posted up to, and the failed attempts of the next post."""

    cursor: int
    attempts: int = 0
    next_attempt_at: datetime | None = None


@dataclass(frozen=True)
class Attempt:
    """One post to a webhook's receiver, for the delivery log."""

    webhook_id: str
    delivery_id: str
    at: datetime
    # How many events the post carried.
    events: int
    # What the receiver answered. None when it could not be reached.
    status: int | None
    # Why the post failed. None when the receiver took it.
    error: str | None


@dataclass(frozen=True)
class WebhookRecord:
    webhook: Webhook
    secret: Sealed
    delivery: Delivery


class WebhookRepository(Protocol):
    def add(self, record: WebhookRecord) -> None: ...

    def get(self, webhook_id: str) -> WebhookRecord:
        """``NotFoundError`` when it is not there."""
        ...

    def list(self) -> list[WebhookRecord]:
        """Oldest first."""
        ...

    def delete(self, webhook_id: str) -> None: ...

    def delete_for_user(self, user_id: str) -> int:
        """Remove every webhook of a user. Returns how many there were."""
        ...

    def update(
        self,
        webhook_id: str,
        delivery: Delivery,
        *,
        last_delivery_at: datetime | None,
        last_error: str | None,
    ) -> None:
        """A webhook that is gone meanwhile changes nothing."""
        ...

    def add_attempt(self, attempt: Attempt, *, keep: int) -> None:
        """Logs a post, keeping the newest ``keep`` of the webhook. A
        webhook that is gone meanwhile logs nothing."""
        ...

    def attempts(self, webhook_id: str) -> builtins.list[Attempt]:
        """The logged posts, newest first."""
        ...


class InMemoryWebhookRepository:
    def __init__(self) -> None:
        self._records: dict[str, WebhookRecord] = {}
        self._attempts: dict[str, list[Attempt]] = {}

    def add(self, record: WebhookRecord) -> None:
        self._records[record.webhook.id] = record

    def get(self, webhook_id: str) -> WebhookRecord:
        record = self._records.get(webhook_id)
        if record is None:
            raise missing("webhook", webhook_id)
        return record

    def list(self) -> list[WebhookRecord]:
        return sorted(self._records.values(), key=lambda r: r.webhook.created_at)

    def delete(self, webhook_id: str) -> None:
        self.get(webhook_id)
        del self._records[webhook_id]
        self._attempts.pop(webhook_id, None)

    def delete_for_user(self, user_id: str) -> int:
        owned = [r.webhook.id for r in self.list() if r.webhook.user_id == user_id]
        for webhook_id in owned:
            self.delete(webhook_id)
        return len(owned)

    def update(
        self,
        webhook_id: str,
        delivery: Delivery,
        *,
        last_delivery_at: datetime | None,
        last_error: str | None,
    ) -> None:
        record = self._records.get(webhook_id)
        if record is None:
            return
        webhook = record.webhook.model_copy(
            update={"last_delivery_at": last_delivery_at, "last_error": last_error}
        )
        self._records[webhook_id] = replace(record, webhook=webhook, delivery=delivery)

    def add_attempt(self, attempt: Attempt, *, keep: int) -> None:
        if attempt.webhook_id not in self._records:
            return
        logged = [attempt, *self._attempts.get(attempt.webhook_id, [])]
        self._attempts[attempt.webhook_id] = logged[:keep]

    def attempts(self, webhook_id: str) -> builtins.list[Attempt]:
        return list(self._attempts.get(webhook_id, []))
