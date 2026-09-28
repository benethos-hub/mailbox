"""Grant constraints on sending, and the audit of every send (CONCEPT 7.5,
7.7).

A send is allowed when one grant that allows it on the account accepts every
recipient and its send limit is not reached. The limit counts the mails the
user sent from the account in the last 24 hours. Every attempt is recorded,
sent, denied or failed, with its recipients and never its content.
"""

from __future__ import annotations

import math
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any, Literal

from ...common.clock import iso, parse_iso, utc_now
from ...common.ids import new_id
from ...data.models import Page, SendFilter, SendOutcome, SendRecord, SentMessage
from ...data.storage import SendLogRepository
from ...errors import (
    MailboxServiceError,
    RecipientNotAllowedError,
    SendLimitError,
)
from .. import paging
from ..activity import ActivityLog, Actor
from ..activity import mailbox as said
from ..locks import KeyedLocks
from ..rights import Access

WINDOW = timedelta(hours=24)
CURSOR = "s_"

Operation = Literal["send_message", "send_draft"]


class SendControl:
    def __init__(
        self,
        store: SendLogRepository,
        clock: Callable[[], datetime] = utc_now,
        activity: ActivityLog | None = None,
    ) -> None:
        self._store = store
        self._clock = clock
        self._activity = activity or ActivityLog(clock)
        # One send at a time per user and account, so two cannot both pass
        # the limit.
        self._locks: KeyedLocks[tuple[str, str]] = KeyedLocks()

    async def send(
        self,
        access: Access,
        operation: Operation,
        account_id: str,
        recipients: list[str],
        action: Callable[[], Awaitable[SentMessage]],
        message_id_header: str,
    ) -> SentMessage:
        """``action``'s result, if the grants allow sending to
        ``recipients``. Recorded either way."""
        async with self._locks.get((access.user_id, account_id)):

            def record(outcome: SendOutcome, **fields: object) -> None:
                self._store.add(
                    SendRecord.model_validate(
                        {
                            "id": new_id("snd"),
                            "created_at": self._clock(),
                            "user_id": access.user_id,
                            "credential_id": access.credential_id,
                            "account_id": account_id,
                            "operation": operation,
                            "recipients": recipients,
                            "outcome": outcome,
                            **fields,
                        }
                    )
                )

            by = Actor.of(access)
            try:
                self._allow(access, operation, account_id, recipients)
            except MailboxServiceError as exc:
                record("denied", error=exc.code)
                self._activity.record(
                    said.SendLimitReached(
                        by=by,
                        account_id=account_id,
                        reason=exc.message,
                        retry_after=exc.retry_after,
                    )
                    if isinstance(exc, SendLimitError)
                    else said.SendRefused(by=by, account_id=account_id, code=exc.code)
                )
                raise
            try:
                sent = await action()
            except MailboxServiceError as exc:
                record("failed", error=exc.code)
                self._activity.record(
                    said.SendFailed(by=by, account_id=account_id, code=exc.code)
                )
                raise
            except Exception:
                record("failed", error="internal_error")
                raise
            # Sent: from here on nothing may fail, or a client would send again.
            with self._activity.fail_quietly(
                lambda exc: said.NotInAudit(by=by, account_id=account_id, error=exc)
            ):
                record(
                    "sent", refused=sent.refused, message_id_header=message_id_header
                )
            return sent

    def _allow(
        self,
        access: Access,
        operation: Operation,
        account_id: str,
        recipients: list[str],
    ) -> None:
        limits = access.send_limits(operation, account_id)
        fitting = [
            limit for limit in limits if all(limit.accepts(r) for r in recipients)
        ]
        if not fitting:
            outside = [r for r in recipients if not any(x.accepts(r) for x in limits)]
            raise RecipientNotAllowedError(
                "no grant allows sending to "
                + (", ".join(outside) if outside else "these recipients together")
            )
        caps = [limit.max_per_day for limit in fitting]
        if any(cap is None for cap in caps):
            return
        cap = max(cap for cap in caps if cap is not None)
        now = self._clock()
        # Only what went out counts. A denied or failed attempt sent nothing.
        sent = self._store.sent_since(
            access.user_id, account_id, now - WINDOW, outcome="sent"
        )
        if len(sent) < cap:
            return
        # The next send is possible once enough of the last day's have aged out.
        free_at = sent[len(sent) - cap] + WINDOW
        raise SendLimitError(
            f"{len(sent)} mails sent from this account in 24 hours, "
            f"the grants allow {cap}",
            retry_after=max(1, math.ceil((free_at - now).total_seconds())),
        )

    def list_all_sends(
        self,
        access: Access,
        *,
        limit: int,
        cursor: str | None = None,
        matching: SendFilter | None = None,
    ) -> Page[SendRecord]:
        """The audit of every account the caller may audit, merged newest
        first. The audit outlives an account: a deleted one is still in it,
        for a caller whose grant names every account."""
        audited = access.filter("list_sends", self._store.account_ids())
        return self._page(audited, limit, cursor, matching)

    def list_sends(
        self,
        access: Access,
        account_id: str,
        *,
        limit: int,
        cursor: str | None,
        matching: SendFilter | None = None,
    ) -> Page[SendRecord]:
        """The audit of an account, newest first."""
        access.require("list_sends", account_id)
        return self._page([account_id], limit, cursor, matching)

    def _page(
        self,
        account_ids: list[str],
        limit: int,
        cursor: str | None,
        matching: SendFilter | None,
    ) -> Page[SendRecord]:
        before = None
        if cursor is not None:
            before = paging.decode_cursor(CURSOR, cursor, _before)
        records: list[SendRecord] = []
        for account_id in account_ids:
            records += self._store.list(
                account_id, limit=limit + 1, before=before, matching=matching
            )
        records.sort(key=lambda record: (record.created_at, record.id), reverse=True)
        records, more = paging.split_page(records, limit)
        next_cursor = None
        if more:
            last = records[-1]
            next_cursor = paging.encode_cursor(CURSOR, [iso(last.created_at), last.id])
        return Page[SendRecord](items=records, next_cursor=next_cursor)


def _before(carried: Any) -> tuple[datetime, str]:
    """The time and the id a cursor of the send log continues before."""
    at, record_id = carried
    return parse_iso(str(at)), str(record_id)
