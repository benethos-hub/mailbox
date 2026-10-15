"""Provider calls under our stable message ids.

Callers name messages by our ids (``sync``), providers by their own. This
module translates between the two, follows a message another client moved,
and keeps the account's status in step with how each call went. Each change
it makes goes into the change feed. It checks no rights: the services that
use it do.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from ...data.models import (
    Abilities,
    Account,
    AttachmentContent,
    Message,
    MessageSummary,
    MessageUpdate,
    Page,
)
from ...data.providers import Reads
from ...data.storage import IndexEntry
from ...errors import MailboxServiceError, MessageNotFoundError, missing_message
from ..accounts import Adapters, Needs, deletes, writes
from ..changes import MailboxChange, MessagesDeleted, MessagesUpdated
from ..sync import SyncService

T = TypeVar("T")
S = TypeVar("S", bound=MessageSummary)


class Calls:
    def __init__(self, adapters: Adapters, sync: SyncService) -> None:
        self._adapters = adapters
        self._sync = sync
        self._gone = Gone()

    # --- the accounts -----------------------------------------------------------------

    def record(self, account_id: str) -> Account:
        return self._adapters.record(account_id)

    def ids(self) -> list[str]:
        return self._adapters.ids()

    async def resync(self, account_id: str) -> None:
        """Bring the account's id mapping up to date now."""
        await self._sync.sync_account(account_id)

    # --- what the account can do -----------------------------------------------------

    async def require(self, account_id: str, wanted: Needs) -> None:
        """Refuse with ``501`` what the account cannot do (UNIFORM R3)."""
        await self._adapters.require(account_id, wanted)

    async def abilities(self, account_id: str) -> Abilities:
        return await self._adapters.abilities(account_id)

    # --- one call ---------------------------------------------------------------------

    async def call(
        self, account_id: str, operation: Callable[[Reads], Awaitable[T]]
    ) -> T:
        """Run one provider operation and keep the account's status in step
        with how it went."""
        return await self._adapters.call(account_id, operation)

    async def on_message(
        self,
        account_id: str,
        message_id: str,
        operation: Callable[[Reads, str], Awaitable[T]],
    ) -> T:
        """Run an operation on the message behind one of our ids. Where
        the provider no longer finds it there, one sync and its new place.
        Anything else it does not find is not ours to follow."""

        def run(native: str) -> Awaitable[T]:
            return self.call(account_id, lambda p: operation(p, native))

        if not self._sync.mapped(account_id):
            return await run(message_id)
        native = self._sync.natives(account_id, [message_id])[message_id]
        if native is None:
            raise missing_message(message_id)
        try:
            return await run(native)
        except MessageNotFoundError:
            moved = await self._after_a_pass(account_id, {message_id: native})
            if message_id not in moved:
                raise missing_message(message_id) from None
            return await run(moved[message_id])

    async def message(self, account_id: str, message_id: str) -> Message:
        """The message behind one of our ids, as the provider names it."""
        return await self.on_message(
            account_id, message_id, lambda p, native: p.get_message(native)
        )

    async def places(self, account_id: str, ids: list[str]) -> dict[str, list[str]]:
        """Each message's folders: from the index, or asked of the provider
        where the account keeps none. Empty for one not found."""
        found: dict[str, list[str]] = {}
        for message_id in ids:
            folder = self._sync.folder_of(account_id, message_id)
            if folder is not None:
                found[message_id] = [folder]
                continue
            try:
                message = await self.message(account_id, message_id)
            except MessageNotFoundError:
                found[message_id] = []
                continue
            found[message_id] = list(message.folder_ids)
        return found

    async def attachment(
        self, account_id: str, message_id: str, attachment_id: str
    ) -> AttachmentContent:
        return await self.on_message(
            account_id,
            message_id,
            lambda p, native: p.get_attachment(native, attachment_id),
        )

    # --- our ids ----------------------------------------------------------------------

    async def published(
        self, account_id: str, items: list[MessageSummary]
    ) -> list[MessageSummary]:
        """The provider's summaries with our ids, the account and, where
        the index keeps them, the threads."""
        ids = await self._sync.public_ids(
            account_id, [(i.id, folder_of(i)) for i in items]
        )
        threads = self._sync.thread_ids(account_id, ids)
        return [
            public(item, our_id, account_id, threads.get(our_id))
            for item, our_id in zip(items, ids, strict=True)
        ]

    async def published_one(
        self, account_id: str, item: MessageSummary
    ) -> MessageSummary:
        [published] = await self.published(account_id, [item])
        return published

    async def published_page(
        self, account_id: str, page: Page[MessageSummary]
    ) -> Page[MessageSummary]:
        return Page[MessageSummary](
            items=await self.published(account_id, page.items),
            next_cursor=page.next_cursor,
        )

    def relocate(self, account_id: str, message_id: str, now: MessageSummary) -> None:
        """A message we stored anew: its id points to the new place."""
        self._sync.relocate(account_id, message_id, now.id, folder_of(now))
        self._sync.changed(
            MessagesUpdated(account_id, [message_id], {message_id: folder_of(now)})
        )

    def changed(self, change: MailboxChange) -> None:
        """Record a change in the change feed."""
        self._sync.changed(change)

    def keeps_threads(self, account_id: str) -> bool:
        """Whether the index keeps the account's threads (IMAP)."""
        return self._sync.keeps_threads(account_id)

    def thread_entries(self, account_id: str, thread_id: str) -> list[IndexEntry]:
        """The index entries of a thread the index keeps."""
        return self._sync.thread_entries(account_id, thread_id)

    def thread_of(self, account_id: str, message_id: str) -> str | None:
        """The thread the index has for a message, None where it keeps no
        threads or has none for it yet."""
        return self._sync.thread_ids(account_id, [message_id]).get(message_id)

    def forget(self, account_id: str, message_id: str) -> None:
        """A message is gone for good: its id answers 404 from now on."""
        was = self._sync.folder_of(account_id, message_id)
        self._sync.forget(account_id, message_id)
        self._sync.changed(
            MessagesDeleted(account_id, [message_id], {message_id: was or ""})
        )

    # --- changes, one or many ---------------------------------------------------------

    async def update(
        self, account_id: str, ids: list[str], changes: MessageUpdate
    ) -> dict[str, MessageSummary | MailboxServiceError]:
        """Change messages. Returns the outcome per id."""
        outcomes, natives = await self._on_messages(
            account_id, ids, lambda p, n: writes(p).update_messages(n, changes)
        )
        results: dict[str, MessageSummary | MailboxServiceError] = {}
        folders: dict[str, str] = {}
        threads = self._sync.thread_ids(account_id, ids)
        for message_id, outcome in outcomes.items():
            if isinstance(outcome, MailboxServiceError):
                results[message_id] = outcome
                continue
            self._follow(account_id, message_id, natives[message_id], outcome)
            results[message_id] = public(
                outcome, message_id, account_id, threads.get(message_id)
            )
            folders[message_id] = folder_of(outcome)
        self._sync.changed(MessagesUpdated(account_id, _done(results), folders))
        return results

    async def update_one(
        self, account_id: str, message_id: str, changes: MessageUpdate
    ) -> MessageSummary:
        """Change one message, raising what a single operation raises."""
        outcome = (await self.update(account_id, [message_id], changes))[message_id]
        if isinstance(outcome, MailboxServiceError):
            raise outcome
        return outcome

    async def delete(
        self, account_id: str, ids: list[str], permanent: bool
    ) -> dict[str, None | MailboxServiceError]:
        """Into the trash, or for good. Returns the outcome per id."""
        outcomes, natives = await self._on_messages(
            account_id, ids, lambda p, n: deletes(p).delete_messages(n, permanent)
        )
        results: dict[str, None | MailboxServiceError] = {}
        folders: dict[str, str] = {}
        for message_id, outcome in outcomes.items():
            if isinstance(outcome, MailboxServiceError):
                results[message_id] = outcome
                continue
            if permanent:
                folders[message_id] = self._sync.folder_of(account_id, message_id) or ""
                self._sync.forget(account_id, message_id)
            elif outcome is not None:
                self._follow(account_id, message_id, natives[message_id], outcome)
                folders[message_id] = folder_of(outcome)
            results[message_id] = None
        done = _done(results)
        self._sync.changed(
            MessagesDeleted(account_id, done, folders)
            if permanent
            else MessagesUpdated(account_id, done, folders)
        )
        return results

    async def delete_one(
        self, account_id: str, message_id: str, permanent: bool
    ) -> None:
        outcome = (await self.delete(account_id, [message_id], permanent))[message_id]
        if isinstance(outcome, MailboxServiceError):
            raise outcome

    def _follow(
        self, account_id: str, message_id: str, native: str, now: MessageSummary
    ) -> None:
        """A message the provider moved: its id points to the new place.
        The caller records the change."""
        if now.id != native:
            self._sync.relocate(account_id, message_id, now.id, folder_of(now))

    async def _on_messages(
        self,
        account_id: str,
        ids: list[str],
        run: Callable[[Reads, list[str]], Awaitable[dict[str, Any]]],
    ) -> tuple[dict[str, Any], dict[str, str]]:
        """Run a provider operation on the messages behind ``ids``. Those
        the provider does not find where the index says get one sync and a
        second try. Returns the outcome per id and the provider id used."""
        natives = {i: n for i, n in self._sync.natives(account_id, ids).items() if n}
        outcomes: dict[str, Any] = {
            i: missing_message(i) for i in ids if i not in natives
        }
        outcomes.update(await self._run_on(account_id, natives, run))
        missing = [i for i in natives if isinstance(outcomes[i], MessageNotFoundError)]
        if missing and self._sync.mapped(account_id):
            moved = await self._after_a_pass(
                account_id, {i: natives[i] for i in missing}
            )
            outcomes.update(await self._run_on(account_id, moved, run))
            natives.update(moved)
        for message_id, outcome in outcomes.items():
            if isinstance(outcome, MessageNotFoundError):
                outcomes[message_id] = MessageNotFoundError(
                    f"message {message_id} not found"
                )
        return outcomes, natives

    async def _after_a_pass(
        self, account_id: str, natives: dict[str, str]
    ) -> dict[str, str]:
        """Messages the provider did not find where the index says: one sync
        pass, and the new place of those that moved. One looked up in vain
        since the last pass gets no pass of its own: a caller that names a
        stale id again and again does not sync the account each time."""
        if self._gone.known(account_id, self._passes(account_id), natives):
            return {}
        await self._sync.sync_account(account_id)
        now = self._sync.natives(account_id, list(natives))
        moved = {i: n for i, n in now.items() if n and n != natives[i]}
        self._gone.note(
            account_id,
            self._passes(account_id),
            {i: n for i, n in natives.items() if i not in moved},
        )
        return moved

    def _passes(self, account_id: str) -> int:
        return self._sync.state(account_id).passes

    async def _run_on(
        self,
        account_id: str,
        natives: dict[str, str],
        run: Callable[[Reads, list[str]], Awaitable[dict[str, Any]]],
    ) -> dict[str, Any]:
        if not natives:
            return {}
        by_native = await self.call(
            account_id, lambda p: run(p, list(natives.values()))
        )
        absent = missing_message()
        return {i: by_native.get(n, absent) for i, n in natives.items()}


class Gone:
    """Per account, the messages looked up in vain after a pass: our id
    and the provider's. Forgotten with the next pass."""

    def __init__(self) -> None:
        self._after: dict[str, tuple[int, set[tuple[str, str]]]] = {}

    def known(self, account_id: str, passes: int, natives: dict[str, str]) -> bool:
        """Whether every one of them was looked up in vain since pass
        ``passes``."""
        noted = self._after.get(account_id)
        return (
            noted is not None
            and noted[0] == passes
            and set(natives.items()) <= noted[1]
        )

    def note(self, account_id: str, passes: int, natives: dict[str, str]) -> None:
        noted = self._after.get(account_id)
        if noted is None or noted[0] != passes:
            noted = (passes, set())
            self._after[account_id] = noted
        noted[1].update(natives.items())


def _done(results: dict[str, Any]) -> list[str]:
    """The ids whose operation succeeded."""
    return [i for i, r in results.items() if not isinstance(r, MailboxServiceError)]


def folder_of(message: MessageSummary) -> str:
    """The provider's folder of a message, empty where it names none."""
    return message.folder_ids[0] if message.folder_ids else ""


def public(
    message: S, message_id: str, account_id: str, thread_id: str | None = None
) -> S:
    """A provider's message under our id, with its account, and with the
    thread the index keeps for it where the provider names none."""
    update = {"id": message_id, "account_id": account_id}
    if thread_id is not None:
        update["thread_id"] = thread_id
    return message.model_copy(update=update)
