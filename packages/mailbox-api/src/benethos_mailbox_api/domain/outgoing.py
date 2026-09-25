"""Sending and drafts: a message composed from the account's address, a
reply or forward made from its original, drafts kept until they are sent.

``MailboxService`` hands its sending and draft operations to ``Outgoing``;
callers keep using the mailbox service.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TypeVar

from pydantic import BaseModel

from ..data.mail import compose
from ..data.models import (
    AttachmentContent,
    DraftMessage,
    Message,
    MessageReference,
    MessageSummary,
    MessageUpdate,
    OutgoingMessage,
    Page,
    Recipient,
    SendRecord,
    SendResult,
    SentMessage,
)
from ..errors import BadRequestError, MailboxApiError
from . import replies
from .access import Access
from .calls import Calls, folder_of, public
from .idempotency import Idempotency
from .sending import SendControl

M = TypeVar("M", bound=DraftMessage)

log = logging.getLogger(__name__)


class Outgoing:
    def __init__(
        self, calls: Calls, idempotency: Idempotency, sends: SendControl
    ) -> None:
        self._calls = calls
        self._accounts = calls.accounts
        self._sync = calls.sync
        self._idempotency = idempotency
        self._sends = sends

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
        access.require("send_message", account_id)
        if message.reference is not None:
            # A reply quotes the original and a forward passes it on: whoever
            # may only send must not get at mail this way.
            access.require("get_message", account_id)
        return await self._idempotency.run(
            account_id,
            idempotency_key,
            "send_message",
            message,
            lambda: self._send(access, account_id, message),
            SendResult,
        )

    async def _send(
        self, access: Access, account_id: str, message: OutgoingMessage
    ) -> SendResult:
        account = self._accounts.record(account_id)
        raw, message_id, message, original = await self._compose(
            account_id, message, draft=False
        )
        # Checked once composed: a reply finds its recipients in the original.
        recipients = message.recipients()
        sent = await self._sends.send(
            access,
            "send_message",
            account_id,
            recipients,
            lambda: self._calls.call(
                account_id, lambda p: p.send(raw, account.email, recipients)
            ),
            message_id,
        )
        if message.reference is not None and original is not None:
            await self._mark_answered(account_id, message.reference, original)
        return await self._send_result(account_id, message_id, sent)

    async def _send_result(
        self, account_id: str, message_id: str, sent: SentMessage
    ) -> SendResult:
        copy_id = None
        if sent.sent_copy is not None:
            copy = sent.sent_copy
            [copy_id] = await self._sync.public_ids(
                account_id, [(copy.id, folder_of(copy))]
            )
        return SendResult(
            message_id_header=message_id, sent_copy_id=copy_id, refused=sent.refused
        )

    def list_sends(
        self, access: Access, account_id: str, *, limit: int, cursor: str | None
    ) -> Page[SendRecord]:
        """The audit of sends from an account, newest first."""
        return self._sends.list_sends(access, account_id, limit=limit, cursor=cursor)

    # --- composing ------------------------------------------------------------------

    async def _compose(
        self, account_id: str, message: M, *, draft: bool
    ) -> tuple[bytes, str, M, Message | None]:
        """The message as bytes, from the account's address, with a fresh
        Date and Message-ID. A reference is filled in from the original.
        Returns the bytes, the Message-ID, the message as filled in and the
        original, if any."""
        account = self._accounts.record(account_id)
        extras = compose.Extras()
        original: Message | None = None
        reference = message.reference
        if reference is not None:
            original = await self._calls.on_message(
                account_id,
                reference.message_id,
                lambda p, native: p.get_message(native),
            )
            message, extras = await self._answer(
                account_id, account.email, message, reference, original
            )
        message_id = compose.new_message_id(account.email)
        raw = compose.message(
            message,
            Recipient(email=account.email, name=account.display_name),
            # Local time with its offset, as mail clients write it.
            datetime.now(UTC).astimezone(),
            message_id,
            extras,
            draft=draft,
            reference=compose.write_reference(reference) if reference else None,
        )
        return raw, message_id, message, original

    async def _answer(
        self,
        account_id: str,
        own_address: str,
        message: M,
        reference: MessageReference,
        original: Message,
    ) -> tuple[M, compose.Extras]:
        """Fetch what the reply or forward needs of the original; ``replies``
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
                content = await self.attachment(
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

    async def attachment(
        self, account_id: str, message_id: str, attachment_id: str
    ) -> AttachmentContent:
        """An attachment's content. Checks no rights."""
        return await self._calls.on_message(
            account_id,
            message_id,
            lambda p, native: p.get_attachment(native, attachment_id),
        )

    async def _mark_answered(
        self, account_id: str, reference: MessageReference, original: Message
    ) -> None:
        """``$answered`` or ``$forwarded`` on the original, so other clients
        show it too. The message is sent already: a failure here is logged."""
        keyword = replies.answered_keyword(reference)
        changes = MessageUpdate(keywords=sorted({*original.keywords, keyword}))
        try:
            outcome = await self._calls.update(
                account_id, [reference.message_id], changes
            )
            failure = outcome[reference.message_id]
            if isinstance(failure, MailboxApiError):
                raise failure
        except MailboxApiError as exc:
            log.warning(
                "sent, but %s not set on the original: %s", keyword, exc.message
            )

    # --- drafts ---------------------------------------------------------------------

    async def list_drafts(
        self, access: Access, account_id: str, *, limit: int, cursor: str | None
    ) -> Page[MessageSummary]:
        access.require("list_drafts", account_id)
        page = await self._calls.call(
            account_id, lambda p: p.list_drafts(limit=limit, cursor=cursor)
        )
        return Page[MessageSummary](
            items=await self._calls.published(account_id, page.items),
            next_cursor=page.next_cursor,
        )

    async def create_draft(
        self, access: Access, account_id: str, draft: DraftMessage
    ) -> MessageSummary:
        """Store a draft in the drafts folder, composed like a message to
        send. A reference is filled in now and remembered for the send."""
        _require_draft_right(access, "create_draft", account_id, draft)
        raw, _, _, _ = await self._compose(account_id, draft, draft=True)
        saved = await self._calls.call(account_id, lambda p: p.save_draft(raw, None))
        [published] = await self._calls.published(account_id, [saved])
        return published

    async def update_draft(
        self, access: Access, account_id: str, draft_id: str, draft: DraftMessage
    ) -> MessageSummary:
        """Replace a draft. It keeps its id, though the provider stores a
        new message and removes the old one."""
        _require_draft_right(access, "update_draft", account_id, draft)
        raw, _, _, _ = await self._compose(account_id, draft, draft=True)
        saved = await self._calls.on_message(
            account_id, draft_id, lambda p, native: p.save_draft(raw, native)
        )
        self._sync.relocate(account_id, draft_id, saved.id, folder_of(saved))
        [our_id] = await self._sync.public_ids(
            account_id, [(saved.id, folder_of(saved))]
        )
        return public(saved, our_id, account_id)

    async def send_draft(
        self,
        access: Access,
        account_id: str,
        draft_id: str,
        idempotency_key: str | None = None,
    ) -> SendResult:
        """Send a draft as it is stored, dated now, then delete it. Its own
        right, like ``send_message``; the draft was written by whoever may
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
        )

    async def _send_draft(
        self, access: Access, account_id: str, draft_id: str
    ) -> SendResult:
        account = self._accounts.record(account_id)
        stored = await self._calls.on_message(
            account_id, draft_id, lambda p, native: p.get_draft(native)
        )
        out = compose.outgoing(
            stored,
            datetime.now(UTC).astimezone(),
            compose.new_message_id(account.email),
        )
        if not out.recipients:
            raise BadRequestError("the draft has no recipients")
        sent = await self._sends.send(
            access,
            "send_draft",
            account_id,
            out.recipients,
            lambda: self._calls.call(
                account_id, lambda p: p.send(out.raw, account.email, out.recipients)
            ),
            out.message_id,
        )
        # Sent: from here on nothing may fail, or a client would send again.
        try:
            await self._calls.on_message(
                account_id, draft_id, lambda p, native: p.delete_draft(native)
            )
            self._sync.forget(account_id, draft_id)
        except MailboxApiError as exc:
            log.warning("sent, but the draft is still there: %s", exc.message)
        if out.reference is not None:
            await self._mark_from_draft(account_id, out.reference)
        return await self._send_result(account_id, out.message_id, sent)

    async def _mark_from_draft(self, account_id: str, header: str) -> None:
        """Mark the original the sent draft answered or forwarded."""
        reference = compose.read_reference(header)
        if reference is None:
            return
        try:
            original = await self._calls.on_message(
                account_id,
                reference.message_id,
                lambda p, native: p.get_message(native),
            )
        except MailboxApiError as exc:
            log.warning("sent, but the original is not marked: %s", exc.message)
            return
        await self._mark_answered(account_id, reference, original)

    async def delete_draft(
        self, access: Access, account_id: str, draft_id: str
    ) -> None:
        """For good: a draft is not kept in the trash."""
        access.require("delete_draft", account_id)
        await self._calls.on_message(
            account_id, draft_id, lambda p, native: p.delete_draft(native)
        )
        self._sync.forget(account_id, draft_id)


class _DraftToSend(BaseModel):
    """What makes two ``send_draft`` requests the same, for Idempotency-Key."""

    draft_id: str


def _require_draft_right(
    access: Access, operation: str, account_id: str, draft: DraftMessage
) -> None:
    access.require(operation, account_id)
    if draft.reference is not None:
        # The draft quotes or carries the original, as a send would.
        access.require("get_message", account_id)
