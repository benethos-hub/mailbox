"""Webhooks: changed, and given a new signing secret, read into
``Webhook`` and ``WebhookSecret``."""

from __future__ import annotations

from datetime import datetime
from types import EllipsisType
from typing import Any

from ..calls import Call, given, path
from ..models import Secret, Webhook, WebhookSecret


def update_webhook(
    webhook_id: str,
    *,
    url: str | None = None,
    events: list[str] | None = None,
    accounts: list[str] | None | EllipsisType = ...,
) -> Call[Webhook]:
    """Where a webhook posts and what. A field left out stays, ``accounts``
    left as ``...`` too. ``accounts`` None is every account its owner may
    read. Its deliveries and its secret stay."""
    body = given({"url": url, "events": events})
    if accounts is not ...:
        body["accounts"] = accounts
    return Call("PATCH", path("webhooks", webhook_id), webhook, json=body)


def renew_webhook_secret(webhook_id: str) -> Call[WebhookSecret]:
    """A new signing secret, shown this once. The one before stops at once."""
    return Call(
        "POST",
        path("webhooks", webhook_id, "secret"),
        lambda found: WebhookSecret(
            webhook_id=str(found["webhook_id"]), secret=Secret(str(found["secret"]))
        ),
    )


def webhook(item: dict[str, Any]) -> Webhook:
    accounts = item.get("accounts")
    return Webhook(
        id=str(item["id"]),
        url=str(item["url"]),
        events=tuple(item["events"]),
        accounts=tuple(accounts) if accounts is not None else None,
        user_id=str(item["user_id"]),
        created_at=_time(item["created_at"]),
        last_delivery_at=_time(item.get("last_delivery_at")),
        last_error=item.get("last_error"),
    )


def _time(value: Any) -> Any:
    """A time of the API, None as None."""
    return datetime.fromisoformat(value) if value else None
