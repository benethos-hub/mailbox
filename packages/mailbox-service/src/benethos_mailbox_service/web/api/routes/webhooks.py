"""Webhooks of the caller."""

from __future__ import annotations

from fastapi import APIRouter, Response

from ....data.models import CreatedWebhook, Webhook, WebhookCreate
from ..deps import Caller, Webhooks

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.get("")
async def list_webhooks(caller: Caller, webhooks: Webhooks) -> list[Webhook]:
    """The caller's webhooks, with how their last delivery went. Never the
    secret."""
    return webhooks.list_webhooks(caller)


@router.post("", status_code=201)
async def create_webhook(
    request: WebhookCreate, caller: Caller, webhooks: Webhooks
) -> CreatedWebhook:
    """Register a URL for events. The answer holds the signing secret, the
    only time it is shown. Each post carries the events since the last one,
    of the accounts the caller may read with `list_changes`."""
    return webhooks.create_webhook(caller, request)


@router.delete("/{webhook_id}", status_code=204)
async def delete_webhook(
    webhook_id: str, caller: Caller, webhooks: Webhooks
) -> Response:
    webhooks.delete_webhook(caller, webhook_id)
    return Response(status_code=204)
