"""Grant constraints on sending, and the audit of every send (CONCEPT 7.5,
7.7).

A send is allowed when one grant that allows it on the account accepts every
recipient and its send limit is not reached. The limit counts the mails the
user sent from the account in the last 24 hours. Every attempt is recorded,
sent, denied or failed, with its recipients and never its content.
"""

from __future__ import annotations

import asyncio
import math
import weakref
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Literal

from ..common import opaque
from ..common.clock import utc_now
from ..common.ids import new_id
from ..data.models import Page, SendOutcome, SendRecord, SentMessage
from ..data.storage import SendLogRepository
from ..errors import (
    BadRequestError,
    MailboxApiError,
    RecipientNotAllowedError,
    SendLimitError,
)
from .access import Access

WINDOW = timedelta(hours=24)
CURSOR = "s_"

Operation = Literal["send_message", "send_draft"]


class SendControl:
    def __init__(
        self,
        store: SendLogRepository,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._store = store
        self._clock = clock
        # One send at a time per user and account, so two cannot both pass
        # the limit.
        self._locks: weakref.WeakValueDictionary[tuple[str, str], asyncio.Lock] = (
            weakref.WeakValueDictionary()
        )

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
        ``recipients``; recorded either way."""
        lock_key = (access.user_id, account_id)
        lock = self._locks.get(lock_key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[lock_key] = lock
        async with lock:

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

            try:
                self._allow(access, operation, account_id, recipients)
            except MailboxApiError as exc:
                record("denied", error=exc.code)
                raise
            try:
                sent = await action()
            except MailboxApiError as exc:
                record("failed", error=exc.code)
                raise
            except Exception:
                record("failed", error="internal_error")
                raise
            record("sent", refused=sent.refused, message_id_header=message_id_header)
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
        sent = self._store.sent_since(access.user_id, account_id, now - WINDOW)
        if len(sent) < cap:
            return
        # The next send is possible once enough of the last day's have aged out.
        free_at = sent[len(sent) - cap] + WINDOW
        raise SendLimitError(
            f"{len(sent)} mails sent from this account in 24 hours, "
            f"the grants allow {cap}",
            retry_after=max(1, math.ceil((free_at - now).total_seconds())),
        )

    def list_sends(
        self, access: Access, account_id: str, *, limit: int, cursor: str | None
    ) -> Page[SendRecord]:
        """The audit of an account, newest first."""
        access.require("list_sends", account_id)
        before = None
        if cursor is not None:
            try:
                at, record_id = opaque.decode(CURSOR, cursor)
                before = (datetime.fromisoformat(at), str(record_id))
            except (ValueError, TypeError):
                raise BadRequestError("invalid cursor") from None
        records = self._store.list(account_id, limit=limit + 1, before=before)
        next_cursor = None
        if len(records) > limit:
            records = records[:limit]
            last = records[-1]
            next_cursor = opaque.encode(CURSOR, [last.created_at.isoformat(), last.id])
        return Page[SendRecord](items=records, next_cursor=next_cursor)
