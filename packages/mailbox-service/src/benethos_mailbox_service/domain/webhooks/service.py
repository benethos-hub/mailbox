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

from ...common.clock import utc_now
from ...common.ids import new_id
from ...data.models import (
    CreatedWebhook,
    Webhook,
    WebhookCreate,
    WebhookDetail,
    WebhookPost,
)
from ...data.secrets import CredentialVault
from ...data.storage import Delivery, WebhookRecord, WebhookRepository
from ...errors import BadRequestError, NotFoundError
from ..activity import ActivityLog, Actor
from ..activity import webhooks as said
from ..changes import ChangeFeed
from ..rights import Access

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
        activity: ActivityLog | None = None,
    ) -> None:
        self._repository = repository
        self._vault = vault
        self._changes = changes
        self._clock = clock
        self._activity = activity or ActivityLog(clock)

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
        self._activity.record(
            said.WebhookCreated(
                by=Actor.of(access),
                webhook_id=webhook_id,
                host=host_of(webhook.url),
                events=tuple(webhook.events),
                accounts=len(webhook.accounts)
                if webhook.accounts is not None
                else None,
            )
        )
        return CreatedWebhook(**webhook.model_dump(), secret=secret)

    def list_webhooks(
        self,
        access: Access,
        *,
        url: str | None = None,
        account: str | None = None,
        failing: bool | None = None,
    ) -> list[Webhook]:
        """The caller's own webhooks. The others narrow the list: a part
        of the URL regardless of case, an account it hears of, whether its
        last post failed."""
        access.require("list_webhooks")
        wanted = (url or "").casefold()
        return [
            hook
            for hook in (r.webhook for r in self._repository.list())
            if hook.user_id == access.user_id
            and wanted in hook.url.casefold()
            and (account is None or hook.accounts is None or account in hook.accounts)
            and (failing is None or (hook.last_error is not None) == failing)
        ]

    def get_webhook(self, access: Access, webhook_id: str) -> WebhookDetail:
        """One of the caller's own webhooks, with its last posts, newest
        first."""
        access.require("get_webhook")
        hook = self._own(access, webhook_id).webhook
        return WebhookDetail(
            **hook.model_dump(),
            deliveries=[
                WebhookPost(
                    delivery_id=a.delivery_id,
                    at=a.at,
                    events=a.events,
                    status=a.status,
                    error=a.error,
                )
                for a in self._repository.attempts(webhook_id)
            ],
        )

    def delete_webhook(self, access: Access, webhook_id: str) -> None:
        access.require("delete_webhook")
        hook = self._own(access, webhook_id).webhook
        self._repository.delete(webhook_id)
        self._activity.record(
            said.WebhookRemoved(
                by=Actor.of(access), webhook_id=webhook_id, host=host_of(hook.url)
            )
        )

    def _own(self, access: Access, webhook_id: str) -> WebhookRecord:
        """Another user's webhook answers as if it did not exist."""
        record = self._repository.get(webhook_id)
        if record.webhook.user_id != access.user_id:
            raise NotFoundError(f"webhook {webhook_id} not found")
        return record


def host_of(url: str) -> str:
    """The host a webhook posts to, for the log: never the whole URL,
    which may carry a key."""
    try:
        return urlsplit(url).hostname or "an unknown host"
    except ValueError:
        return "an unknown host"


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
