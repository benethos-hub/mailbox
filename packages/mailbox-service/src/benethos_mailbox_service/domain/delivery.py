"""Posting events to webhooks (CONCEPT 6.5).

The events come from the log behind the change feed. Each webhook keeps
the point it has posted up to, so a restart loses nothing and posts
nothing twice that a receiver took. A post carries up to ``BATCH`` events,
of the accounts the webhook's creator may read now. It is signed with the
webhook's secret: ``X-Mailbox-Signature: t=<unix time>,v1=<hex>``, the
HMAC-SHA256 of ``<unix time>.`` followed by the body.

A post the receiver does not take with a 2xx is tried again, after
``first_retry`` seconds, then twice as long each time up to
``longest_retry``. After ``attempts`` tries its events are dropped, the
webhook notes why, and the next post starts after them.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Protocol

import anyio

from .. import __version__
from ..common.clock import utc_now
from ..common.ids import new_id
from ..data.secrets import CredentialVault
from ..data.storage import Delivery, WebhookRecord, WebhookRepository
from ..errors import MailboxServiceError
from .access import Access
from .changes import ChangeFeed
from .webhooks import sealed_label

BATCH = 100
# How often the log is looked at for new events, in seconds.
POLL = 5.0
# Posts of one webhook in one round, so one busy webhook does not hold up
# the others.
ROUND = 10

Sleep = Callable[[float], Awaitable[None]]

log = logging.getLogger(__name__)


class Poster(Protocol):
    async def post(self, url: str, body: bytes, headers: dict[str, str]) -> int: ...


@dataclass(frozen=True)
class Retries:
    attempts: int = 8
    first_retry: float = 30.0
    longest_retry: float = 3600.0

    def pause(self, failed: int) -> timedelta:
        """How long to wait after the ``failed``-th failed attempt."""
        seconds = min(self.longest_retry, self.first_retry * 2 ** (failed - 1))
        return timedelta(seconds=seconds)


DEFAULT_RETRIES = Retries()


def signature(secret: str, timestamp: int, body: bytes) -> str:
    """The value of ``X-Mailbox-Signature`` for a body."""
    signed = f"{timestamp}.".encode() + body
    digest = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


class WebhookDispatcher:
    def __init__(
        self,
        repository: WebhookRepository,
        vault: CredentialVault,
        changes: ChangeFeed,
        poster: Poster,
        *,
        access_of: Callable[[str], Access | None],
        account_ids: Callable[[], list[str]],
        retries: Retries = DEFAULT_RETRIES,
        clock: Callable[[], datetime] = utc_now,
        sleep: Sleep = anyio.sleep,
    ) -> None:
        self._repository = repository
        self._vault = vault
        self._changes = changes
        self._poster = poster
        self._access_of = access_of
        self._account_ids = account_ids
        self._retries = retries
        self._clock = clock
        self._sleep = sleep

    async def run(self) -> None:
        """Until cancelled."""
        while True:
            await self.deliver_due()
            await self._sleep(POLL)

    async def deliver_due(self) -> None:
        """One round over every webhook that is due."""
        for record in self._repository.list():
            try:
                for _ in range(ROUND):
                    if not await self._deliver(record.webhook.id):
                        break
            except MailboxServiceError as exc:
                log.warning("webhook %s: %s", record.webhook.id, exc.message)

    async def _deliver(self, webhook_id: str) -> bool:
        """One post, if one is due. True when more events wait."""
        try:
            record = self._repository.get(webhook_id)
        except MailboxServiceError:
            return False  # removed meanwhile
        now = self._clock()
        delivery = record.delivery
        if delivery.next_attempt_at is not None and delivery.next_attempt_at > now:
            return False
        note = record.webhook.last_error
        # Read first: an event logged meanwhile is posted now or next time.
        last = self._changes.last()
        horizon = self._changes.horizon()
        if delivery.cursor < horizon:
            delivery = replace(delivery, cursor=horizon)
            note = "events were purged before they could be posted"
        access = self._access_of(record.webhook.user_id)
        accounts = self._accounts(record, access)
        found = self._changes.after(
            accounts,
            delivery.cursor,
            limit=BATCH + 1,
            types=frozenset(record.webhook.events),
        )
        if not found:
            if delivery.cursor != last or note != record.webhook.last_error:
                self._save(record, replace(delivery, cursor=last), note)
            return False
        more = len(found) > BATCH
        batch = found[:BATCH]
        body = json.dumps(
            {
                "webhook_id": record.webhook.id,
                "delivery_id": new_id("dlv"),
                "events": [e.event.model_dump(mode="json") for e in batch],
                "more": more,
            },
            separators=(",", ":"),
        ).encode()
        error = await self._post(record, body, now)
        end = batch[-1].seq
        if error is None:
            self._save(
                record,
                Delivery(cursor=end),
                note if note != record.webhook.last_error else None,
                delivered_at=now,
            )
            return more
        failed = delivery.attempts + 1
        if failed >= self._retries.attempts:
            self._save(
                record,
                Delivery(cursor=end),
                f"{error}. {len(batch)} events were dropped after {failed} attempts",
            )
            return more
        self._save(
            record,
            replace(
                delivery,
                attempts=failed,
                next_attempt_at=now + self._retries.pause(failed),
            ),
            error,
        )
        return False

    def _accounts(self, record: WebhookRecord, access: Access | None) -> list[str]:
        """The accounts the webhook hears of: its own list or every one,
        of those its creator may read now. None without a creator."""
        if access is None:
            return []
        wanted = record.webhook.accounts
        candidates = wanted if wanted is not None else self._account_ids()
        return [a for a in candidates if access.allows("list_changes", a)]

    async def _post(
        self, record: WebhookRecord, body: bytes, now: datetime
    ) -> str | None:
        """None when the receiver took it, else why not."""
        secret = self._vault.unseal(sealed_label(record.webhook.id), record.secret)
        timestamp = int(now.timestamp())
        headers = {
            "Content-Type": "application/json",
            "User-Agent": f"benethos-mailbox-service/{__version__}",
            "X-Mailbox-Webhook-Id": record.webhook.id,
            "X-Mailbox-Signature": signature(
                secret.get_secret_value(), timestamp, body
            ),
        }
        try:
            status = await self._poster.post(record.webhook.url, body, headers)
        except MailboxServiceError as exc:
            return exc.message
        if 200 <= status < 300:
            return None
        return f"the receiver answered {status}"

    def _save(
        self,
        record: WebhookRecord,
        delivery: Delivery,
        error: str | None,
        *,
        delivered_at: datetime | None = None,
    ) -> None:
        self._repository.update(
            record.webhook.id,
            delivery,
            last_delivery_at=delivered_at or record.webhook.last_delivery_at,
            last_error=error,
        )
