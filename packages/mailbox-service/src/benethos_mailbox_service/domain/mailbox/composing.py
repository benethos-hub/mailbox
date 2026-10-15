"""A message composed to send or keep as a draft: from the account's
address, with a fresh Date and Message-ID, a reply or forward made from
its original, the attachments it names of other messages fetched."""

from __future__ import annotations

import base64
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Generic, TypeVar

from benethos_mailbox_common.values import text

from ...data.mail import compose
from ...data.models import (
    DraftMessage,
    Message,
    MessageReference,
    OutgoingAttachment,
    Recipient,
)
from ...errors import missing_message
from ..rights import Access
from . import checks, replies
from .calls import Calls
from .reach import reach_of

M = TypeVar("M", bound=DraftMessage)


@dataclass(frozen=True, slots=True)
class Composed(Generic[M]):
    """A message as bytes, its Message-ID, the message as filled in, and
    the original a reference named, if any."""

    raw: bytes
    message_id: str
    message: M
    original: Message | None


class Composer:
    def __init__(self, calls: Calls, clock: Callable[[], datetime]) -> None:
        self._calls = calls
        self._clock = clock

    async def make(
        self, access: Access, account_id: str, message: M, *, draft: bool
    ) -> Composed[M]:
        """The message as bytes, from the account's address, with a fresh
        Date and Message-ID. A reference is filled in from the original,
        which must be in a folder the caller may read."""
        account = self._calls.record(account_id)
        extras = compose.NO_EXTRAS
        original: Message | None = None
        reference = message.reference
        if reference is not None:
            original = await self._calls.message(account_id, reference.message_id)
            reach = await reach_of(self._calls, access, "get_message", account_id)
            if reach is not None and not reach.sees(original.folder_ids):
                raise missing_message(reference.message_id)
            message, extras = await self._answer(
                account_id, account.email, message, reference, original
            )
        message_id = compose.new_message_id(account.email)
        raw = compose.message(
            message,
            # One stored before names were checked may break a line.
            Recipient.model_construct(
                email=account.email,
                name=text.joined(account.display_name or "") or None,
            ),
            self.date(),
            message_id,
            extras,
            draft=draft,
            reference=compose.write_reference(reference) if reference else None,
        )
        return Composed(raw, message_id, message, original)

    def date(self) -> datetime:
        """Now, in local time with its offset, as mail clients write it."""
        return self._clock().astimezone()

    async def with_sources(self, access: Access, account_id: str, message: M) -> M:
        """``message`` with the attachments it names of other messages
        fetched, before its own. Each message must be in a folder the
        caller may read attachments in."""
        if not message.attachments_from:
            return message
        reach = await reach_of(self._calls, access, "get_attachment", account_id)
        fetched = []
        for source in message.attachments_from:
            if reach is not None:
                holder = await self._calls.message(account_id, source.message_id)
                if not reach.sees(holder.folder_ids):
                    raise missing_message(source.message_id)
            fetched.append(
                await self.attachment(
                    account_id, source.message_id, source.attachment_id
                )
            )
        attachments = [*fetched, *message.attachments]
        checks.sized(attachments)
        return message.model_copy(
            update={"attachments": attachments, "attachments_from": []}
        )

    async def attachment(
        self, account_id: str, message_id: str, attachment_id: str
    ) -> OutgoingAttachment:
        """An attachment of a stored message, to attach again."""
        found = await self._calls.attachment(account_id, message_id, attachment_id)
        return OutgoingAttachment(
            filename=found.filename or attachment_id,
            content_type=found.content_type,
            data=base64.b64encode(found.data),
        )

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
