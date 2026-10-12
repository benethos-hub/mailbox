"""Threads where the index keeps them: for an adapter with ``THREADS``
but no thread ids of its own (IMAP).

A message joins the thread of any message its ``Message-ID``,
``In-Reply-To`` or ``References`` names, in any folder, also of one that
came later or is gone. Where it ties two threads together, the younger
goes into the older. Entries from before threads are threaded a portion
per sync pass.
"""

from __future__ import annotations

from collections.abc import Callable

from benethos_mailbox_common.values import secret

from ...common.chunks import batched
from ...data.providers import Capability, ThreadHeaders
from ...data.storage import IndexEntry, MessageIndexRepository, ThreadChain
from ...errors import MailboxServiceError
from ..accounts import Adapters
from .passes import chain

# Of the References of a message, the last ones kept to find its thread.
REFERENCES = 20
# Entries from before threads, threaded in one pass at most.
THREADED_PER_PASS = 2000
# Messages threaded in one transaction, so that others wait only briefly.
THREADED_AT_ONCE = 500


def new_thread_id() -> str:
    return secret.new_id("thr")


class IndexThreads:
    def __init__(
        self,
        adapters: Adapters,
        index: MessageIndexRepository,
        references: int = REFERENCES,
        new_thread: Callable[[], str] = new_thread_id,
    ) -> None:
        self._adapters = adapters
        self._index = index
        self._references = references
        self._new_thread = new_thread

    def kept(self, account_id: str) -> bool:
        """Whether the index keeps the account's threads."""
        able = self._adapters.capabilities(account_id)
        return Capability.THREADS in able and Capability.STABLE_IDS not in able

    def of(self, account_id: str, message_ids: list[str]) -> dict[str, str]:
        """The thread of each message the index has one for. Empty where
        the index keeps no threads."""
        if not self.kept(account_id):
            return {}
        return self._index.threads_of(account_id, message_ids)

    def join(
        self,
        account_id: str,
        entries: list[IndexEntry],
        headers: dict[str, ThreadHeaders],
    ) -> dict[str, str]:
        """New entries into their threads, by the headers read for them.
        Those without headers wait for a later pass. Answers the messages
        whose thread went into another, each with its thread now."""
        if not self.kept(account_id):
            return {}
        return self._thread(
            account_id,
            [
                chain(e.id, headers[e.native_id], self._references)
                for e in entries
                if e.native_id in headers
            ],
        )

    async def backfill(self, account_id: str) -> dict[str, str]:
        """A portion of the entries without a thread into theirs, with
        their headers read now. Best effort: the next pass tries again. A
        message the provider has no headers for is a thread of its own."""
        if not self.kept(account_id):
            return {}
        entries = self._index.unthreaded(account_id, THREADED_PER_PASS)
        if not entries:
            return {}
        natives = [e.native_id for e in entries]
        try:
            headers = await self._adapters.call(
                account_id, lambda p: p.message_headers(natives)
            )
        except MailboxServiceError:
            return {}
        return self._thread(
            account_id,
            [
                chain(e.id, headers.get(e.native_id, ThreadHeaders()), self._references)
                for e in entries
            ],
        )

    def moved(
        self, account_id: str, merged: dict[str, str], created: set[str]
    ) -> dict[str, str]:
        """Of the messages whose thread went into another, those not new
        in this pass, each with its folder."""
        return {
            entry.id: entry.folder_id
            for message_id in merged
            if message_id not in created
            and (entry := self._index.get(account_id, message_id)) is not None
        }

    def _thread(self, account_id: str, chains: list[ThreadChain]) -> dict[str, str]:
        merged: dict[str, str] = {}
        for part in batched(chains, THREADED_AT_ONCE):
            merged.update(self._index.thread(account_id, part, self._new_thread))
        return merged
