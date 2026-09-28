"""Sending and drafts: a message composed from the account's address, a
reply or forward made from its original, drafts kept until they are sent.

``MailboxService`` holds it as ``outgoing``, where both front ends reach
it.
"""

from __future__ import annotations

import base64
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import TypeVar

from pydantic import BaseModel

from ...common.clock import utc_now
from ...data.mail import compose, convert
from ...data.models import (
    Account,
    Address,
    DraftMessage,
    Message,
    MessageReference,
    MessageSummary,
    MessageUpdate,
    OutgoingAttachment,
    OutgoingMessage,
    Page,
    Recipient,
    SendFilter,
    SendRecord,
    SendResult,
    SentMessage,
)
from ...errors import BadRequestError, MailboxServiceError
from .. import changes
from ..activity import ActivityLog, Actor
from ..activity.catalogue.mailbox import MessageSent, SentBut
from ..rights import Access
from . import replies
from .calls import Calls
from .idempotency import Idempotency
from .sending import Operation, SendControl

M = TypeVar("M", bound=DraftMessage)

# What one message may carry.
MAX_RECIPIENTS = 100
MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024


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
        self._clock = clock
        self._activity = activity or ActivityLog(clock)

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
        _require(access, "send_message", account_id, message)
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
        raw, message_id, message, original = await self._compose(
            account_id, message, draft=False
        )
        # Checked once composed: a reply finds its recipients in the original.
        recipients = _addressed(message.recipients())
        account = self._calls.record(account_id)
        result = await self._deliver(
            access, "send_message", account, raw, recipients, message_id
        )
        if message.reference is not None and original is not None:
            with self._after_sending(access, account, "the original is not marked"):
                await self._mark_answered(account_id, message.reference, original)
        return result

    async def _deliver(
        self,
        access: Access,
        operation: Operation,
        account: Account,
        raw: bytes,
        recipients: list[str],
        message_id: str,
    ) -> SendResult:
        """Hand a composed message to the provider, under the grants'
        constraints and recorded in the audit."""
        account_id = account.id
        sent = await self._sends.send(
            access,
            operation,
            account_id,
            recipients,
            lambda: self._calls.call(
                account_id, lambda p: p.send(raw, account.email, recipients)
            ),
            message_id,
        )
        result = await self._send_result(access, account, message_id, sent)
        self._activity.record(
            MessageSent(
                by=Actor.of(access),
                account=account,
                recipients=len(recipients),
                message=result.sent_copy_id or message_id,
            )
        )
        return result

    async def _send_result(
        self, access: Access, account: Account, message_id: str, sent: SentMessage
    ) -> SendResult:
        """What the caller learns of a send. The message is sent already: the
        bookkeeping here is logged when it fails, never raised, or a client
        would send again."""
        account_id = account.id
        if sent.copy_error is not None:
            self._activity.record(
                SentBut(
                    by=Actor.of(access),
                    account=account,
                    what="no copy is in the sent folder",
                    error=MailboxServiceError(sent.copy_error),
                )
            )
        copy_id = None
        with self._after_sending(
            access, account, "the sent copy or the change is not recorded"
        ):
            if sent.sent_copy is not None:
                copy = await self._calls.published_one(account_id, sent.sent_copy)
                copy_id = copy.id
            self._calls.changed(changes.MessageSent(account_id, copy_id or message_id))
        return SendResult(
            message_id_header=message_id, sent_copy_id=copy_id, refused=sent.refused
        )

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
        limit: int,
        cursor: str | None = None,
        matching: SendFilter | None = None,
    ) -> Page[SendRecord]:
        """The sends of every account the caller may audit, newest first."""
        return self._sends.list_all_sends(
            access, limit=limit, cursor=cursor, matching=matching
        )

    # --- composing ------------------------------------------------------------------

    async def _compose(
        self, account_id: str, message: M, *, draft: bool
    ) -> tuple[bytes, str, M, Message | None]:
        """The message as bytes, from the account's address, with a fresh
        Date and Message-ID. A reference is filled in from the original.
        Returns the bytes, the Message-ID, the message as filled in and the
        original, if any."""
        account = self._calls.record(account_id)
        extras = compose.Extras()
        original: Message | None = None
        reference = message.reference
        if reference is not None:
            original = await self._calls.message(account_id, reference.message_id)
            message, extras = await self._answer(
                account_id, account.email, message, reference, original
            )
        message_id = compose.new_message_id(account.email)
        raw = compose.message(
            message,
            Recipient(email=account.email, name=account.display_name),
            self._date(),
            message_id,
            extras,
            draft=draft,
            reference=compose.write_reference(reference) if reference else None,
        )
        return raw, message_id, message, original

    def _date(self) -> datetime:
        """Now, in local time with its offset, as mail clients write it."""
        return self._clock().astimezone()

    async def _answer(
        self,
        account_id: str,
        own_address: str,
        message: M,
        reference: MessageReference,
        original: Message,
    ) -> tuple[M, compose.Extras]:
        """Fetch what the reply or forward needs of the original. ``replies``
        makes it."""
        raw = await self._calls.on_message(
            account_id, reference.message_id, lambda p, native: p.get_raw(native)
        )
        if reference.action != "forward":
            return replies.reply(
                message, reference.action, original, raw, own_address, reference.quote
            )
        files: list[replies.AttachedFile] = []
        if reference.forward_as == "inline" and reference.quote:
            for attachment in original.attachments:
                content = await self._calls.attachment(
                    account_id, reference.message_id, attachment.id
                )
                files.append(
                    (
                        attachment.filename or attachment.id,
                        attachment.content_type,
                        content.data,
                    )
                )
        return replies.forward(
            message, reference.forward_as, original, raw, files, reference.quote
        )

    async def _mark_answered(
        self, account_id: str, reference: MessageReference, original: Message
    ) -> None:
        """``$answered`` or ``$forwarded`` on the original, so other clients
        show it too. Called after the message went out, where a failure is
        logged."""
        keyword = replies.answered_keyword(reference)
        changes = MessageUpdate(keywords=sorted({*original.keywords, keyword}))
        await self._calls.update_one(account_id, reference.message_id, changes)

    # --- drafts ---------------------------------------------------------------------

    async def list_drafts(
        self, access: Access, account_id: str, *, limit: int, cursor: str | None
    ) -> Page[MessageSummary]:
        access.require("list_drafts", account_id)
        page = await self._calls.call(
            account_id, lambda p: p.list_drafts(limit=limit, cursor=cursor)
        )
        return await self._calls.published_page(account_id, page)

    async def create_draft(
        self, access: Access, account_id: str, draft: DraftMessage
    ) -> MessageSummary:
        """Store a draft in the drafts folder, composed like a message to
        send. A reference is filled in now and remembered for the send."""
        _require(access, "create_draft", account_id, draft)
        raw, _, composed, _ = await self._compose(account_id, draft, draft=True)
        _limited(composed.recipients())
        saved = await self._calls.call(account_id, lambda p: p.save_draft(raw, None))
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
        """Replace a draft. It keeps its id, though the provider stores a
        new message and removes the old one. ``keep_attachments``: ids of
        attachments of the stored draft that go into the new one, before
        those the draft brings."""
        _require(access, "update_draft", account_id, draft)
        # The draft, before anything of it is read: whoever may write
        # drafts may not read other mail this way.
        raw = await self._calls.on_message(
            account_id, draft_id, lambda p, native: p.get_draft(native)
        )
        if _same(convert.stored_draft(raw), draft, keep_attachments):
            # Stored as it is: the provider is left alone.
            stored = await self._calls.message(account_id, draft_id)
            return await self._calls.published_one(account_id, stored)
        if keep_attachments:
            kept = [
                await self._kept_attachment(account_id, draft_id, attachment_id)
                for attachment_id in keep_attachments
            ]
            draft = draft.model_copy(update={"attachments": kept + draft.attachments})
        raw, _, composed, _ = await self._compose(account_id, draft, draft=True)
        _limited(composed.recipients())
        saved = await self._calls.on_message(
            account_id, draft_id, lambda p, native: p.save_draft(raw, native)
        )
        self._calls.relocate(account_id, draft_id, saved)
        return await self._calls.published_one(account_id, saved)

    async def _kept_attachment(
        self, account_id: str, draft_id: str, attachment_id: str
    ) -> OutgoingAttachment:
        found = await self._calls.attachment(account_id, draft_id, attachment_id)
        return OutgoingAttachment(
            filename=found.filename or attachment_id,
            content_type=found.content_type,
            data=base64.b64encode(found.data),
        )

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
            account_id, draft_id, lambda p, native: p.get_draft(native)
        )
        out = compose.outgoing(
            stored, self._date(), compose.new_message_id(account.email)
        )
        recipients = _addressed(out.recipients)
        result = await self._deliver(
            access, "send_draft", account, out.raw, recipients, out.message_id
        )
        # Sent: from here on nothing may fail, or a client would send again.
        with self._after_sending(access, account, "the draft is still there"):
            await self._delete_draft(account_id, draft_id)
        if out.reference is not None:
            with self._after_sending(access, account, "the original is not marked"):
                await self._mark_from_draft(account_id, out.reference)
        return result

    async def _mark_from_draft(self, account_id: str, header: str) -> None:
        """Mark the original the sent draft answered or forwarded."""
        reference = compose.read_reference(header)
        if reference is None:
            return
        original = await self._calls.message(account_id, reference.message_id)
        await self._mark_answered(account_id, reference, original)

    @contextmanager
    def _after_sending(
        self, access: Access, account: Account, what: str
    ) -> Iterator[None]:
        """A step after the message went out. It may fail, but only into
        the log: the send succeeded, and a client told otherwise sends
        again."""
        try:
            yield
        except Exception as exc:
            self._activity.record(
                SentBut(by=Actor.of(access), account=account, what=what, error=exc)
            )

    async def delete_draft(
        self, access: Access, account_id: str, draft_id: str
    ) -> None:
        """For good: a draft is not kept in the trash."""
        access.require("delete_draft", account_id)
        await self._delete_draft(account_id, draft_id)

    async def _delete_draft(self, account_id: str, draft_id: str) -> None:
        await self._calls.on_message(
            account_id, draft_id, lambda p, native: p.delete_draft(native)
        )
        self._calls.forget(account_id, draft_id)


class _DraftToSend(BaseModel):
    """What makes two ``send_draft`` requests the same, for Idempotency-Key."""

    draft_id: str


def _require(
    access: Access, operation: str, account_id: str, message: DraftMessage
) -> None:
    """The operation's right and, with a reference, the right to read: a
    reply quotes the original and a forward passes it on. Whoever may only
    send or write drafts must not get at mail this way. Then the size."""
    access.require(operation, account_id)
    if message.reference is not None:
        access.require("get_message", account_id)
    if sum(len(a.data) for a in message.attachments) > MAX_ATTACHMENT_BYTES:
        raise BadRequestError("the attachments exceed 25 MB")


def _limited(recipients: list[str]) -> list[str]:
    """No more recipients than the service carries. Checked once composed:
    a reply takes its recipients from the original."""
    if len(recipients) > MAX_RECIPIENTS:
        raise BadRequestError(f"at most {MAX_RECIPIENTS} recipients")
    return recipients


def _addressed(recipients: list[str]) -> list[str]:
    """A message to send needs at least one recipient. A reply finds them
    in the original, a forward or a plain message brings its own."""
    if not recipients:
        raise BadRequestError("a message needs at least one recipient")
    return _limited(recipients)


def _same(
    stored: convert.StoredDraft, draft: DraftMessage, keep: list[str] | None
) -> bool:
    """Whether ``draft`` is the draft as it is stored: the same addresses,
    subject, bodies and original, every attachment kept and none added.
    Whitespace counts as one space, as a form sends a text back."""
    if draft.attachments or sorted(keep or []) != sorted(stored.attachment_ids):
        return False
    if draft.reference is not None and draft.reference.quote:
        return False  # composing adds the quote again

    def people(values: list[Recipient] | list[Address]) -> list[tuple[str, str]]:
        return [(v.email.lower(), (v.name or "").strip()) for v in values]

    def words(value: str | None) -> str:
        return " ".join((value or "").split())

    def original(reference: MessageReference | None) -> tuple[str, ...] | None:
        if reference is None:
            return None
        return (reference.message_id, reference.action, reference.forward_as)

    return (
        people(draft.to) == people(stored.to)
        and people(draft.cc) == people(stored.cc)
        and people(draft.bcc) == people(stored.bcc)
        and people(draft.reply_to) == people(stored.reply_to)
        and words(draft.subject) == words(stored.subject)
        and (draft.text is None or words(draft.text) == words(stored.text))
        and words(draft.html) == words(stored.html)
        and original(draft.reference) == original(stored.reference)
    )
