"""Webhooks and where each one's delivery stands. The repository only
stores. The domain decides what is posted, and when."""

from __future__ import annotations

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


class InMemoryWebhookRepository:
    def __init__(self) -> None:
        self._records: dict[str, WebhookRecord] = {}

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
