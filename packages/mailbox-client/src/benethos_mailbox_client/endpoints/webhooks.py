"""Webhooks: listed, made, read with their last posts, changed, given a
new signing secret and removed, read into ``Webhook`` and the records
around it. A secret comes back once, as a ``Secret``."""

from __future__ import annotations

from types import EllipsisType
from typing import Any

from ..calls import Call, given, nothing, path
from ..models import (
    NewWebhook,
    Secret,
    Webhook,
    WebhookDetail,
    WebhookPost,
    WebhookSecret,
)
from .readings import maybe_time, time


def list_webhooks(
    *,
    url: str | None = None,
    account: str | None = None,
    failing: bool | None = None,
) -> Call[list[Webhook]]:
    """The caller's own webhooks. ``url`` a part of it regardless of case,
    ``account`` those that hear of it, ``failing`` whether the last post
    failed."""
    return Call(
        "GET",
        path("webhooks"),
        lambda found: [webhook(w) for w in found],
        params=given({"url": url, "account": account, "failing": failing}),
    )


def create_webhook(
    url: str,
    *,
    events: list[str] | None = None,
    accounts: list[str] | None = None,
) -> Call[NewWebhook]:
    """Register ``url`` for ``events``, without them every event, of
    ``accounts``, without them every account the caller may read, accounts
    added later included. Its signing secret comes back this once."""
    return Call(
        "POST",
        path("webhooks"),
        lambda found: NewWebhook(
            webhook=webhook(found), secret=Secret(str(found["secret"]))
        ),
        json=given({"url": url, "events": events, "accounts": accounts}),
    )


def get_webhook(webhook_id: str) -> Call[WebhookDetail]:
    """One of the caller's webhooks with its last posts, newest first."""
    return Call(
        "GET",
        path("webhooks", webhook_id),
        lambda found: WebhookDetail(
            webhook=webhook(found),
            deliveries=tuple(
                WebhookPost(
                    delivery_id=str(d["delivery_id"]),
                    at=time(d["at"]),
                    events=int(d["events"]),
                    status=d.get("status"),
                    error=d.get("error"),
                )
                for d in found["deliveries"]
            ),
        ),
    )


def delete_webhook(webhook_id: str) -> Call[None]:
    """The service stops posting to it. What it posted stays with the
    receiver."""
    return Call("DELETE", path("webhooks", webhook_id), nothing)


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
        created_at=time(item["created_at"]),
        last_delivery_at=maybe_time(item.get("last_delivery_at")),
        last_error=item.get("last_error"),
    )
