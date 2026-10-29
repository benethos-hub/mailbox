"""Sending and drafts: a message composed from the account's address, a
reply or forward made from its original, drafts kept until they are sent.
Composing is in ``composing``, handing a message to the provider and
what follows in ``delivering``.

``MailboxService`` holds it as ``outgoing``, where both front ends reach
it.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from pydantic import BaseModel

from ....common.clock import utc_now
from ....data.mail import compose, convert
from ....data.models import (
    DraftMessage,
    MessageSummary,
    OutgoingMessage,
    Page,
    SendFilter,
    SendRecord,
    SendResult,
)
from ...accounts import NEEDS, drafts
from ...activity import ActivityLog
from ...rights import Access
from ..calls import Calls
from . import checks
from .composing import Composer
from .delivering import Delivery
from .idempotency import Idempotency
from .sending import SendControl


class Outgoing:
    def __init__(
        self,
        calls: Calls,
        idempotency: Idempotency,
        sends: SendControl,
        clock: Callable[[], datetime] = utc_now,
        activity: ActivityLog | None = None,
    ) -> None:
        self._calls = calls
        self._idempotency = idempotency
        self._sends = sends
        self._composer = Composer(calls, clock)
        self._delivery = Delivery(calls, sends, activity or ActivityLog(clock))

    # --- sending --------------------------------------------------------------------

    async def send_message(
        self,
        access: Access,
        account_id: str,
        message: OutgoingMessage,
        idempotency_key: str | None = None,
    ) -> SendResult:
        """Send from the account's address, with a fresh Date and
        Message-ID. Its own right: sending cannot be taken back. With an
        ``idempotency_key`` a retry returns the first result."""
        checks.require(access, "send_message", account_id, message)
        await self._calls.require(account_id, NEEDS["send_message"])
        return await self._idempotency.run(
            account_id,
            idempotency_key,
            "send_message",
            message,
            lambda: self._send(access, account_id, message),
            SendResult,
            user_id=access.user_id,
        )

    async def _send(
        self, access: Access, account_id: str, message: OutgoingMessage
    ) -> SendResult:
        message = await self._composer.with_sources(access, account_id, message)
        composed = await self._composer.make(access, account_id, message, draft=False)
        message, original = composed.message, composed.original
        # Checked once composed: a reply finds its recipients in the original.
        recipients = checks.addressed(message.recipients())
        account = self._calls.record(account_id)
        result = await self._delivery.deliver(
            access,
            "send_message",
            account,
            composed.raw,
            recipients,
            composed.message_id,
        )
        if message.reference is not None and original is not None:
            marked = False
            with self._delivery.after_sending(
                access, account, "the original is not marked"
            ):
                marked = await self._delivery.mark_answered(
                    account_id, message.reference, original
                )
            result = result.model_copy(update={"original_marked": marked})
        return result

    def list_sends(
        self,
        access: Access,
        account_id: str,
        *,
        limit: int,
        cursor: str | None,
        matching: SendFilter | None = None,
    ) -> Page[SendRecord]:
        """The audit of sends from an account, newest first."""
        return self._sends.list_sends(
            access, account_id, limit=limit, cursor=cursor, matching=matching
        )

    def list_all_sends(
        self,
        access: Access,
        *,
        account_ids: list[str] | None = None,
        limit: int,
        cursor: str | None = None,
        matching: SendFilter | None = None,
    ) -> Page[SendRecord]:
        """The sends of every account the caller may audit, or of those of
        ``account_ids`` among them, newest first."""
        return self._sends.list_all_sends(
            access,
            account_ids=account_ids,
            limit=limit,
            cursor=cursor,
            matching=matching,
        )

    # --- drafts ---------------------------------------------------------------------

    async def list_drafts(
        self, access: Access, account_id: str, *, limit: int, cursor: str | None
    ) -> Page[MessageSummary]:
        access.require("list_drafts", account_id)
        await self._calls.require(account_id, NEEDS["list_drafts"])
        page = await self._calls.call(
            account_id, lambda p: drafts(p).list_drafts(limit=limit, cursor=cursor)
        )
        return await self._calls.published_page(account_id, page)

    async def create_draft(
        self, access: Access, account_id: str, draft: DraftMessage
    ) -> MessageSummary:
        """Store a draft in the drafts folder, composed like a message to
        send. A reference is filled in now and remembered for the send."""
        checks.require(access, "create_draft", account_id, draft)
        await self._calls.require(account_id, NEEDS["create_draft"])
        draft = await self._composer.with_sources(access, account_id, draft)
        composed = await self._composer.make(access, account_id, draft, draft=True)
        checks.limited(composed.message.recipients())
        saved = await self._calls.call(
            account_id, lambda p: drafts(p).save_draft(composed.raw, None)
        )
        return await self._calls.published_one(account_id, saved)

    async def update_draft(
        self,
        access: Access,
        account_id: str,
        draft_id: str,
        draft: DraftMessage,
        *,
        keep_attachments: list[str] | None = None,
    ) -> MessageSummary:
        """Replace a draft. The provider stores a new message and removes
        the old one. The draft as stored, with the id it has from now on:
        the same where the domain maps ids (IMAP), else the provider's new
        one (Microsoft, JMAP). ``keep_attachments``: ids of attachments of
        the stored draft that go into the new one, before those the draft
        brings."""
        checks.require(access, "update_draft", account_id, draft)
        await self._calls.require(account_id, NEEDS["update_draft"])
        # The draft, before anything of it is read: whoever may write
        # drafts may not read other mail this way.
        raw = await self._calls.on_message(
            account_id, draft_id, lambda p, native: drafts(p).get_draft(native)
        )
        if checks.unchanged(convert.stored_draft(raw), draft, keep_attachments):
            # Stored as it is: the provider is left alone.
            stored = await self._calls.message(account_id, draft_id)
            return await self._calls.published_one(account_id, stored)
        draft = await self._composer.with_sources(access, account_id, draft)
        if keep_attachments:
            kept = [
                await self._composer.attachment(account_id, draft_id, attachment_id)
                for attachment_id in keep_attachments
            ]
            draft = draft.model_copy(update={"attachments": kept + draft.attachments})
        composed = await self._composer.make(access, account_id, draft, draft=True)
        checks.limited(composed.message.recipients())
        saved = await self._calls.on_message(
            account_id,
            draft_id,
            lambda p, native: drafts(p).save_draft(composed.raw, native),
        )
        self._calls.relocate(account_id, draft_id, saved)
        return await self._calls.published_one(account_id, saved)

    async def send_draft(
        self,
        access: Access,
        account_id: str,
        draft_id: str,
        idempotency_key: str | None = None,
    ) -> SendResult:
        """Send a draft as it is stored, dated now, then delete it. Its own
        right, like ``send_message``. The draft was written by whoever may
        write drafts. With an ``idempotency_key`` a retry returns the first
        result."""
        access.require("send_draft", account_id)
        await self._calls.require(account_id, NEEDS["send_draft"])
        return await self._idempotency.run(
            account_id,
            idempotency_key,
            "send_draft",
            _DraftToSend(draft_id=draft_id),
            lambda: self._send_draft(access, account_id, draft_id),
            SendResult,
            user_id=access.user_id,
        )

    async def _send_draft(
        self, access: Access, account_id: str, draft_id: str
    ) -> SendResult:
        account = self._calls.record(account_id)
        stored = await self._calls.on_message(
            account_id, draft_id, lambda p, native: drafts(p).get_draft(native)
        )
        out = compose.outgoing(
            stored, self._composer.date(), compose.new_message_id(account.email)
        )
        recipients = checks.addressed(out.recipients)
        result = await self._delivery.deliver(
            access, "send_draft", account, out.raw, recipients, out.message_id
        )
        # Sent: from here on nothing may fail, or a client would send again.
        with self._delivery.after_sending(access, account, "the draft is still there"):
            await self._delete_draft(account_id, draft_id)
        if out.reference is not None:
            marked = False
            with self._delivery.after_sending(
                access, account, "the original is not marked"
            ):
                marked = await self._delivery.mark_from_draft(
                    access, account_id, out.reference
                )
            result = result.model_copy(update={"original_marked": marked})
        return result

    async def delete_draft(
        self, access: Access, account_id: str, draft_id: str
    ) -> None:
        """For good: a draft is not kept in the trash."""
        access.require("delete_draft", account_id)
        await self._calls.require(account_id, NEEDS["delete_draft"])
        await self._delete_draft(account_id, draft_id)

    async def _delete_draft(self, account_id: str, draft_id: str) -> None:
        await self._calls.on_message(
            account_id, draft_id, lambda p, native: drafts(p).delete_draft(native)
        )
        self._calls.forget(account_id, draft_id)


class _DraftToSend(BaseModel):
    """What makes two ``send_draft`` requests the same, for Idempotency-Key."""

    draft_id: str
