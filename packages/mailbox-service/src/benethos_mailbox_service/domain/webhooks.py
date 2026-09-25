"""Webhooks: register, list and remove (CONCEPT 6.5).

A webhook belongs to the user who created it. It hears of the accounts
that user may read, checked again at every delivery, so a right taken
away also stops the webhook. The signing secret is shown once, when the
webhook is created, and kept sealed with the data key.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from datetime import datetime
from urllib.parse import urlsplit

from pydantic import SecretStr

from ..common.clock import utc_now
from ..common.ids import new_id
from ..data.models import CreatedWebhook, Webhook, WebhookCreate
from ..data.secrets import CredentialVault
from ..data.storage import Delivery, WebhookRecord, WebhookRepository
from ..errors import BadRequestError, NotFoundError
from .access import Access
from .changes import ChangeFeed

# Every secret starts so, so a person can tell what it is.
SECRET_PREFIX = "whsec_"


def sealed_label(webhook_id: str) -> str:
    """What a webhook's secret is bound to when sealed."""
    return f"webhook:{webhook_id}"


class WebhookService:
    def __init__(
        self,
        repository: WebhookRepository,
        vault: CredentialVault,
        changes: ChangeFeed,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._repository = repository
        self._vault = vault
        self._changes = changes
        self._clock = clock

    def create_webhook(self, access: Access, request: WebhookCreate) -> CreatedWebhook:
        access.require("create_webhook")
        _check_url(request.url)
        for account_id in request.accounts or []:
            access.require("list_changes", account_id)
        webhook_id = new_id("whk")
        secret = SECRET_PREFIX + secrets.token_urlsafe(32)
        webhook = Webhook(
            id=webhook_id,
            url=request.url,
            events=list(dict.fromkeys(request.events)),
            accounts=(
                list(dict.fromkeys(request.accounts))
                if request.accounts is not None
                else None
            ),
            user_id=access.user_id,
            created_at=self._clock(),
        )
        sealed = self._vault.seal(sealed_label(webhook_id), SecretStr(secret))
        # It hears of what happens from now on.
        delivery = Delivery(cursor=self._changes.last())
        self._repository.add(WebhookRecord(webhook, sealed, delivery))
        return CreatedWebhook(**webhook.model_dump(), secret=secret)

    def list_webhooks(self, access: Access) -> list[Webhook]:
        """The caller's own webhooks."""
        access.require("list_webhooks")
        return [
            r.webhook
            for r in self._repository.list()
            if r.webhook.user_id == access.user_id
        ]

    def delete_webhook(self, access: Access, webhook_id: str) -> None:
        access.require("delete_webhook")
        self._own(access, webhook_id)
        self._repository.delete(webhook_id)

    def _own(self, access: Access, webhook_id: str) -> WebhookRecord:
        """Another user's webhook answers as if it did not exist."""
        record = self._repository.get(webhook_id)
        if record.webhook.user_id != access.user_id:
            raise NotFoundError(f"webhook {webhook_id} not found")
        return record


def _check_url(url: str) -> None:
    """http or https with a host, and no credentials in it. A host in the
    local network is allowed: webhooks are registered on purpose."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise BadRequestError("the webhook url is not a url") from None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise BadRequestError("the webhook url must be http or https, with a host")
    if parts.username is not None or parts.password is not None:
        raise BadRequestError("the webhook url must not carry credentials")
    if port == 0:
        raise BadRequestError("the webhook url has no valid port")
