"""Webhooks of the caller."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Response

from ....data.models import (
    CreatedWebhook,
    Webhook,
    WebhookCreate,
    WebhookDetail,
    WebhookSecret,
    WebhookUpdate,
)
from ..deps import Caller, Webhooks

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.get("")
async def list_webhooks(
    caller: Caller,
    webhooks: Webhooks,
    url: Annotated[
        str | None, Query(description="Part of the URL, regardless of case")
    ] = None,
    account: Annotated[
        str | None,
        Query(
            description=(
                "An account id: the webhooks that hear of it, those of every "
                "account among them"
            )
        ),
    ] = None,
    failing: Annotated[
        bool | None, Query(description="Whether the last post failed")
    ] = None,
) -> list[Webhook]:
    """The caller's webhooks, with how their last delivery went. Never the
    secret. The filter parameters narrow the list together."""
    return webhooks.list_webhooks(caller, url=url, account=account, failing=failing)


@router.post("", status_code=201)
async def create_webhook(
    request: WebhookCreate, caller: Caller, webhooks: Webhooks
) -> CreatedWebhook:
    """Register a URL for events. The answer holds the signing secret, the
    only time it is shown. Each post carries the events since the last one,
    of the accounts the caller may read with `list_changes`."""
    return webhooks.create_webhook(caller, request)


@router.get("/{webhook_id}")
async def get_webhook(
    webhook_id: str, caller: Caller, webhooks: Webhooks
) -> WebhookDetail:
    """One of the caller's webhooks, with its last posts to the receiver:
    when, how many events, what it answered and why a post failed."""
    return webhooks.get_webhook(caller, webhook_id)


@router.patch("/{webhook_id}")
async def update_webhook(
    webhook_id: str, request: WebhookUpdate, caller: Caller, webhooks: Webhooks
) -> Webhook:
    """Change where one of the caller's webhooks posts and what. A field
    left out stays as it is, `accounts` set to `null` is every account the
    caller may read. Its deliveries, where its posts stand and its secret
    stay."""
    return webhooks.update_webhook(caller, webhook_id, request)


@router.post("/{webhook_id}/secret")
async def renew_webhook_secret(
    webhook_id: str, caller: Caller, webhooks: Webhooks
) -> WebhookSecret:
    """A new signing secret for one of the caller's webhooks. The answer
    holds it, the only time it is shown. The one before stops at once: the
    next post is signed with the new one."""
    return webhooks.renew_webhook_secret(caller, webhook_id)


@router.delete("/{webhook_id}", status_code=204)
async def delete_webhook(
    webhook_id: str, caller: Caller, webhooks: Webhooks
) -> Response:
    webhooks.delete_webhook(caller, webhook_id)
    return Response(status_code=204)
