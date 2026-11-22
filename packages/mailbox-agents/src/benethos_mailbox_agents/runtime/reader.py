"""The mailbox as an agent reads it: a message and a thread, nothing more.

An agent is handed this view, never the mailbox itself, so the only way
to change a message is to ask the executor. See
docs/mailbox-agents/concept/agent-contract.md.
"""

from __future__ import annotations

from ..contract import Reader
from ..records import MailMessage, MessageRef, Thread

__all__ = ["ReadOnlyMailbox"]


class ReadOnlyMailbox:
    """Reads through to a mailbox and offers nothing that writes."""

    __slots__ = ("_mailbox",)

    def __init__(self, mailbox: Reader) -> None:
        self._mailbox = mailbox

    async def message(self, ref: MessageRef) -> MailMessage:
        return await self._mailbox.message(ref)

    async def thread(self, account_id: str, thread_id: str) -> Thread:
        return await self._mailbox.thread(account_id, thread_id)
