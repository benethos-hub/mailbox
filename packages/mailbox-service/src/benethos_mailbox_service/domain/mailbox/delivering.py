"""A composed message handed to the provider, under the grants'
constraints and recorded in the audit, and what follows once it went
out: what the caller learns, the original marked as answered or
forwarded. A step after the send may fail into the log only: a client
told otherwise sends again."""

from __future__ import annotations

from contextlib import AbstractContextManager

from ...data.mail import compose
from ...data.models import (
    Account,
    Message,
    MessageReference,
    MessageUpdate,
    SendResult,
    SentMessage,
)
from ...errors import MailboxServiceError
from .. import changes
from ..accounts import sends
from ..activity import ActivityLog, Actor
from ..activity import mailbox as said
from ..rights import Access
from . import replies
from .calls import Calls
from .reach import reach_of
from .sending import Operation, SendControl


class Delivery:
    def __init__(self, calls: Calls, sends: SendControl, activity: ActivityLog) -> None:
        self._calls = calls
        self._sends = sends
        self._activity = activity

    async def deliver(
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
                account_id, lambda p: sends(p).send(raw, account.email, recipients)
            ),
            message_id,
        )
        result = await self._result(access, account, message_id, sent)
        self._activity.record(
            said.MessageSent(
                by=Actor.of(access),
                account=account,
                recipients=len(recipients),
                message=result.sent_copy_id or message_id,
            )
        )
        return result

    def after_sending(
        self, access: Access, account: Account, what: str
    ) -> AbstractContextManager[None]:
        """A step after the message went out. It may fail, but only into
        the log: the send succeeded, and a client told otherwise sends
        again."""
        return self._activity.fail_quietly(
            lambda exc: said.SentBut(
                by=Actor.of(access), account=account, what=what, error=exc
            )
        )

    async def mark_answered(
        self, account_id: str, reference: MessageReference, original: Message
    ) -> bool:
        """``$answered`` or ``$forwarded`` on the original, so other clients
        show it too, where the account writes that mark. Called after the
        message went out, where a failure is logged. Whether the original
        carries the mark now."""
        keyword = replies.answered_keyword(reference)
        if keyword in original.keywords:
            return True
        able = await self._calls.abilities(account_id)
        if keyword not in able.marks.written:
            return False
        update = MessageUpdate(add_keywords=[keyword])
        await self._calls.update_one(account_id, reference.message_id, update)
        return True

    async def mark_from_draft(
        self, access: Access, account_id: str, header: str
    ) -> bool:
        """Mark the original the sent draft answered or forwarded. Any
        client that writes drafts may have named it, so only where the
        caller may change that message itself."""
        reference = compose.read_reference(header)
        if reference is None or not access.allows("update_message", account_id):
            return False
        original = await self._calls.message(account_id, reference.message_id)
        reach = await reach_of(self._calls, access, "update_message", account_id)
        if reach is not None and not reach.sees(original.folder_ids):
            return False
        return await self.mark_answered(account_id, reference, original)

    async def _result(
        self, access: Access, account: Account, message_id: str, sent: SentMessage
    ) -> SendResult:
        """What the caller learns of a send. The message is sent already: the
        bookkeeping here is logged when it fails, never raised, or a client
        would send again."""
        account_id = account.id
        if sent.copy_error is not None:
            self._activity.record(
                said.SentBut(
                    by=Actor.of(access),
                    account=account,
                    what="no copy is in the sent folder",
                    error=MailboxServiceError(sent.copy_error),
                )
            )
        copy_id = None
        with self.after_sending(
            access, account, "the sent copy or the change is not recorded"
        ):
            if sent.sent_copy is not None:
                copy = await self._calls.published_one(account_id, sent.sent_copy)
                copy_id = copy.id
            self._calls.changed(changes.MessageSent(account_id, copy_id or message_id))
        return SendResult(
            message_id_header=message_id, sent_copy_id=copy_id, refused=sent.refused
        )
