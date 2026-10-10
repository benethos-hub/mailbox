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

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Protocol

import anyio

from benethos_mailbox_common.values import canonical

from ... import __version__
from ...common.clock import utc_now
from ...common.ratelimit import backoff
from ...common.secret import hmac_hex, new_id
from ...data.models import ChangeRecord
from ...data.secrets import CredentialVault
from ...data.storage import (
    Attempt,
    Delivery,
    LoggedChange,
    WebhookRecord,
    WebhookRepository,
)
from ...errors import MailboxServiceError
from ..activity import DISPATCHER, ActivityLog
from ..activity import webhooks as said
from ..changes import ChangeFeed
from ..rights import Access
from ..rounds import rounds
from .service import sealed_label

# How the dispatcher waits: anyio.sleep, or a fake in tests.
Sleep = Callable[[float], Awaitable[None]]
# What of an account's changes a creator may hear of, None for all.
Hearing = Callable[[Access, str], Awaitable[Callable[[ChangeRecord], bool] | None]]

BATCH = 100
# How often the log is looked at for new events, in seconds.
POLL = 5.0
# Posts of one webhook in one round, so one busy webhook does not hold up
# the others.
ROUND = 10
# Posts of each webhook kept for its delivery log.
LOGGED = 20


class Poster(Protocol):
    async def post(self, url: str, body: bytes, headers: dict[str, str]) -> int: ...


@dataclass(frozen=True)
class Retries:
    attempts: int = 8
    first_retry: float = 30.0
    longest_retry: float = 3600.0

    def pause(self, failed: int) -> timedelta:
        """How long to wait after the ``failed``-th failed attempt: the
        backoff, without jitter."""
        seconds = backoff(
            failed - 1, self.first_retry, self.longest_retry, jitter=_longest
        )
        return timedelta(seconds=seconds)


def _longest(_shortest: float, longest: float) -> float:
    return longest


DEFAULT_RETRIES = Retries()


def _of_the_account(record: ChangeRecord) -> bool:
    """Only what is not about a message."""
    return not record.type.startswith("message.")


def signature(secret: str, timestamp: int, body: bytes) -> str:
    """The value of ``X-Mailbox-Signature`` for a body."""
    signed = f"{timestamp}.".encode() + body
    return f"t={timestamp},v1={hmac_hex(secret, signed)}"


@dataclass(frozen=True)
class _Pending:
    """What a webhook has to post: where it stands, the note it keeps, the
    newest event of the log, its creator's rights, and the next batch."""

    delivery: Delivery
    note: str | None
    last: int
    access: Access | None
    window: list[LoggedChange]
    more: bool

    @property
    def end(self) -> int:
        return self.window[-1].seq

    def moved(self, record: WebhookRecord) -> bool:
        """Whether there is anything to save without a post."""
        return (
            self.delivery.cursor != self.last or self.note != record.webhook.last_error
        )


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
        hearing: Hearing | None = None,
        retries: Retries = DEFAULT_RETRIES,
        clock: Callable[[], datetime] = utc_now,
        sleep: Sleep = anyio.sleep,
        activity: ActivityLog | None = None,
    ) -> None:
        self._repository = repository
        self._vault = vault
        self._changes = changes
        self._poster = poster
        self._access_of = access_of
        self._account_ids = account_ids
        self._hearing = hearing
        self._retries = retries
        self._clock = clock
        self._sleep = sleep
        self._activity = activity or ActivityLog(clock)

    async def run(self) -> None:
        """Until cancelled. A failure ends a round, never the dispatcher."""
        await rounds(
            self.deliver_due,
            pause=POLL,
            sleep=self._sleep,
            activity=self._activity,
            by=DISPATCHER,
        )

    async def deliver_due(self) -> None:
        """One round over every webhook that is due."""
        for record in self._repository.list():
            try:
                for _ in range(ROUND):
                    if not await self._deliver(record.webhook.id):
                        break
            except Exception as exc:
                # A bug with one webhook must not stop the others.
                self._activity.record(
                    said.WebhookFailed(
                        by=DISPATCHER, webhook_id=record.webhook.id, error=exc
                    )
                )

    async def _deliver(self, webhook_id: str) -> bool:
        """One post, if one is due. True when more events wait."""
        try:
            record = self._repository.get(webhook_id)
        except MailboxServiceError:
            return False  # removed meanwhile
        now = self._clock()
        due = record.delivery.next_attempt_at
        if due is not None and due > now:
            return False
        pending = self._pending(record)
        if not pending.window:
            if pending.moved(record):
                self._save(
                    record, replace(pending.delivery, cursor=pending.last), pending.note
                )
            return False
        batch = await self._heard(pending.access, pending.window)
        if not batch:
            # Nothing the creator may hear of: past it, without a post.
            self._save(
                record, replace(pending.delivery, cursor=pending.end), pending.note
            )
            return pending.more
        error = await self._attempt(record, batch, pending.more, now)
        if error is None:
            self._delivered(record, pending, now)
            return pending.more
        return self._failed(record, pending, len(batch), error, now)

    def _pending(self, record: WebhookRecord) -> _Pending:
        """The events the webhook has not posted yet, up to a batch."""
        delivery = record.delivery
        note = record.webhook.last_error
        # Read first: an event logged meanwhile is posted now or next time.
        last = self._changes.last()
        horizon = self._changes.horizon()
        if delivery.cursor < horizon:
            delivery = replace(delivery, cursor=horizon)
            note = "events were purged before they could be posted"
        access = self._access_of(record.webhook.user_id)
        found = self._changes.after(
            self._accounts(record, access),
            delivery.cursor,
            limit=BATCH + 1,
            types=frozenset(record.webhook.events),
        )
        return _Pending(
            delivery, note, last, access, found[:BATCH], more=len(found) > BATCH
        )

    async def _attempt(
        self,
        record: WebhookRecord,
        batch: list[LoggedChange],
        more: bool,
        now: datetime,
    ) -> str | None:
        """One post of ``batch``, kept in the delivery log. None when the
        receiver took it, else why not."""
        delivery_id = new_id("dlv")
        body = canonical.compact(
            {
                "webhook_id": record.webhook.id,
                "delivery_id": delivery_id,
                "events": [e.record.model_dump(mode="json") for e in batch],
                "more": more,
            }
        ).encode()
        status, error = await self._post(record, body, now)
        self._repository.add_attempt(
            Attempt(record.webhook.id, delivery_id, now, len(batch), status, error),
            keep=LOGGED,
        )
        return error

    def _delivered(
        self, record: WebhookRecord, pending: _Pending, now: datetime
    ) -> None:
        if pending.delivery.attempts or record.webhook.last_error is not None:
            self._activity.record(
                said.DeliversAgain(by=DISPATCHER, webhook_id=record.webhook.id)
            )
        self._save(
            record,
            Delivery(cursor=pending.end),
            pending.note if pending.note != record.webhook.last_error else None,
            delivered_at=now,
        )

    def _failed(
        self,
        record: WebhookRecord,
        pending: _Pending,
        events: int,
        error: str,
        now: datetime,
    ) -> bool:
        """After a post the receiver did not take: another try later, or
        after the last one its events dropped. True when more events wait."""
        failed = pending.delivery.attempts + 1
        if failed >= self._retries.attempts:
            self._activity.record(
                said.GaveUp(
                    by=DISPATCHER,
                    webhook_id=record.webhook.id,
                    changes=events,
                    attempts=failed,
                    reason=error,
                )
            )
            self._save(
                record,
                Delivery(cursor=pending.end),
                f"{error}. {events} events were dropped after {failed} attempts",
            )
            return pending.more
        self._activity.record(
            said.PostFailed(
                by=DISPATCHER,
                webhook_id=record.webhook.id,
                attempt=failed,
                attempts=self._retries.attempts,
                reason=error,
            )
        )
        self._save(
            record,
            replace(
                pending.delivery,
                attempts=failed,
                next_attempt_at=now + self._retries.pause(failed),
            ),
            error,
        )
        return False

    async def _heard(
        self, access: Access | None, window: list[LoggedChange]
    ) -> list[LoggedChange]:
        """The changes the creator may hear of, where its grants name
        folders (PERMISSIONS.md 8.5). An account whose folders cannot be
        read now gives none of its changes of messages."""
        if self._hearing is None or access is None:
            return window
        hearing: dict[str, Callable[[ChangeRecord], bool] | None] = {}
        for account_id in dict.fromkeys(e.record.account_id for e in window):
            try:
                hearing[account_id] = await self._hearing(access, account_id)
            except MailboxServiceError:
                hearing[account_id] = _of_the_account
        return [
            e
            for e in window
            if (hears := hearing[e.record.account_id]) is None or hears(e.record)
        ]

    def _accounts(self, record: WebhookRecord, access: Access | None) -> list[str]:
        """The accounts the webhook hears of: its own list or every one,
        of those its creator may read now. None without a creator."""
        if access is None:
            return []
        wanted = record.webhook.accounts
        candidates = wanted if wanted is not None else self._account_ids()
        return access.filter("list_changes", candidates)

    async def _post(
        self, record: WebhookRecord, body: bytes, now: datetime
    ) -> tuple[int | None, str | None]:
        """What the receiver answered, and None when it took the post,
        else why not."""
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
            return None, exc.message
        if 200 <= status < 300:
            return status, None
        return status, f"the receiver answered {status}"

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
