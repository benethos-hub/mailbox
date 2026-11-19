"""Provider calls under our stable message ids.

Callers name messages by our ids (``sync``), providers by their own. This
module translates between the two, follows a message another client moved,
and keeps the account's status in step with how each call went. Each change
it makes goes into the change feed. It checks no rights: the services that
use it do.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import AbstractContextManager, nullcontext
from functools import partial
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
from ...data.providers import Places, Reads
from ...data.storage import IndexEntry
from ...errors import MailboxServiceError, MessageNotFoundError, missing_message
from ..accounts import Adapters, Needs, deletes, drafts, writes
from ..changes import MailboxChange, MessagesDeleted, MessagesUpdated
from ..sync import SyncService

T = TypeVar("T")
S = TypeVar("S", bound=MessageSummary)
# The outcome of an operation per message: what it answered, or why not.
Outcomes = dict[str, T | MailboxServiceError]


class Calls:
    def __init__(self, adapters: Adapters, sync: SyncService) -> None:
        self._adapters = adapters
        self._sync = sync

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
        return await self._on_message(account_id, message_id, operation, nullcontext)

    async def _written(
        self,
        account_id: str,
        message_id: str,
        operation: Callable[[Reads, str], Awaitable[T]],
        then: Callable[[T], None],
    ) -> T:
        """``on_message`` as a change of ours, under ``writing`` of the
        sync, with ``then`` following it in the index. The pass it may ask
        for itself is paused, so that it does not count as overtaking."""
        with self._sync.writing(account_id):
            done = await self._on_message(
                account_id,
                message_id,
                operation,
                partial(self._sync.pausing, account_id),
            )
            then(done)
        return done

    async def _on_message(
        self,
        account_id: str,
        message_id: str,
        operation: Callable[[Reads, str], Awaitable[T]],
        around_a_pass: Callable[[], AbstractContextManager[Any]],
    ) -> T:
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
            with around_a_pass():
                moved = await self._sync.follow(account_id, {message_id: native})
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
                found[message_id] = await self.on_message(
                    account_id, message_id, _folders_of
                )
            except MessageNotFoundError:
                found[message_id] = []
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
        self, account_id: str, items: list[MessageSummary], *, listed: bool
    ) -> list[MessageSummary]:
        """The provider's summaries with our ids, the account and, where
        the index keeps them, the threads. ``listed``: they come from a
        list, which follows a message another program moved. False for
        a message we stored ourselves just now."""
        ids = await self._sync.public_ids(
            account_id, [(i.id, folder_of(i)) for i in items], listed=listed
        )
        threads = self._sync.thread_ids(account_id, ids)
        return [
            public(item, our_id, account_id, threads.get(our_id))
            for item, our_id in zip(items, ids, strict=True)
        ]

    async def published_one(
        self, account_id: str, item: MessageSummary
    ) -> MessageSummary:
        """A message we stored ourselves just now: its id is given without a
        sync first."""
        [published] = await self.published(account_id, [item], listed=False)
        return published

    async def published_page(
        self, account_id: str, page: Page[MessageSummary]
    ) -> Page[MessageSummary]:
        return Page[MessageSummary](
            items=await self.published(account_id, page.items, listed=True),
            next_cursor=page.next_cursor,
        )

    async def replace_draft(
        self, account_id: str, draft_id: str, raw: bytes
    ) -> MessageSummary:
        """Store ``raw`` in place of a draft. Its id follows the new place
        before a sync pass may read, as with every change of ours."""
        return await self._written(
            account_id,
            draft_id,
            lambda p, native: drafts(p).save_draft(raw, native),
            lambda saved: _relocated(self._sync, account_id, draft_id, saved),
        )

    async def delete_draft(self, account_id: str, draft_id: str) -> None:
        """A draft deleted for good, its id gone with it before a sync pass
        may read."""
        await self._written(
            account_id,
            draft_id,
            lambda p, native: drafts(p).delete_draft(native),
            lambda _: _forgotten(self._sync, account_id, draft_id),
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

    # --- changes, one or many ---------------------------------------------------------

    async def update(
        self, account_id: str, ids: list[str], changes: MessageUpdate
    ) -> dict[str, MessageSummary | MailboxServiceError]:
        """Change messages. Returns the outcome per id."""
        results: dict[str, MessageSummary | MailboxServiceError] = {}
        folders: dict[str, str] = {}

        def settle(message_id: str, native: str, outcome: MessageSummary) -> None:
            _follow(self._sync, account_id, message_id, native, outcome)
            folders[message_id] = folder_of(outcome)

        with self._sync.writing(account_id):
            outcomes = await self._on_messages(
                account_id,
                ids,
                lambda p, n: writes(p).update_messages(n, changes),
                settle,
            )
            threads = self._sync.thread_ids(account_id, ids)
            for message_id, outcome in outcomes.items():
                if isinstance(outcome, MailboxServiceError):
                    results[message_id] = outcome
                    continue
                results[message_id] = public(
                    outcome, message_id, account_id, threads.get(message_id)
                )
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
        results: dict[str, None | MailboxServiceError] = {}
        folders: dict[str, str] = {}

        def settle(
            message_id: str, native: str, outcome: MessageSummary | None
        ) -> None:
            if permanent:
                was = self._sync.folder_of(account_id, message_id)
                folders[message_id] = was or ""
                self._sync.forget(account_id, message_id)
            elif outcome is not None:
                _follow(self._sync, account_id, message_id, native, outcome)
                folders[message_id] = folder_of(outcome)

        with self._sync.writing(account_id):
            outcomes = await self._on_messages(
                account_id,
                ids,
                lambda p, n: deletes(p).delete_messages(n, permanent),
                settle,
            )
            for message_id, outcome in outcomes.items():
                if isinstance(outcome, MailboxServiceError):
                    results[message_id] = outcome
                else:
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

    async def _on_messages(
        self,
        account_id: str,
        ids: list[str],
        run: Callable[[Reads, list[str]], Awaitable[Outcomes[T]]],
        settle: Callable[[str, str, T], None],
    ) -> Outcomes[T]:
        """Run a provider operation on the messages behind ``ids``. Those
        the provider does not find where the index says get one sync and a
        second try. ``settle`` brings the index in line with each success,
        given our id and the provider id used, before a pass reads: the
        pass must find the moves of this change where they are. Returns
        the outcome per id. Called inside ``writing`` of the sync."""
        natives = {i: n for i, n in self._sync.natives(account_id, ids).items() if n}
        outcomes: Outcomes[T] = {i: missing_message(i) for i in ids if i not in natives}
        first = await self._run_on(account_id, natives, run)
        _settle_each(first, natives, settle)
        outcomes.update(first)
        missing = [i for i in natives if isinstance(outcomes[i], MessageNotFoundError)]
        if missing and self._sync.mapped(account_id):
            # The pass looks for them: it must not count this change.
            with self._sync.pausing(account_id):
                moved = await self._sync.follow(
                    account_id, {i: natives[i] for i in missing}
                )
            second = await self._run_on(account_id, moved, run)
            _settle_each(second, moved, settle)
            outcomes.update(second)
        for message_id, outcome in outcomes.items():
            if isinstance(outcome, MessageNotFoundError):
                outcomes[message_id] = missing_message(message_id)
        return outcomes

    async def _run_on(
        self,
        account_id: str,
        natives: dict[str, str],
        run: Callable[[Reads, list[str]], Awaitable[Outcomes[T]]],
    ) -> Outcomes[T]:
        if not natives:
            return {}
        by_native = await self.call(
            account_id, lambda p: run(p, list(natives.values()))
        )
        absent = missing_message()
        return {i: by_native.get(n, absent) for i, n in natives.items()}


async def _folders_of(provider: Reads, native: str) -> list[str]:
    """A message's folders, read without its content where the provider
    can."""
    if isinstance(provider, Places):
        found = await provider.folders_of([native])
        if native not in found:
            raise missing_message(native)
        return found[native]
    return list((await provider.get_message(native)).folder_ids)


def _settle_each(
    outcomes: Outcomes[T],
    natives: dict[str, str],
    settle: Callable[[str, str, T], None],
) -> None:
    """``settle`` for each success among ``outcomes``."""
    for message_id, outcome in outcomes.items():
        if not isinstance(outcome, MailboxServiceError):
            settle(message_id, natives[message_id], outcome)


def _follow(
    sync: SyncService,
    account_id: str,
    message_id: str,
    native: str,
    now: MessageSummary,
) -> None:
    """A message the provider moved: its id points to the new place. The
    caller records the change."""
    if now.id != native:
        sync.relocate(account_id, message_id, now.id, folder_of(now))


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


def _relocated(
    sync: SyncService, account_id: str, message_id: str, now: MessageSummary
) -> None:
    """A message we stored anew: its id points to the new place."""
    sync.relocate(account_id, message_id, now.id, folder_of(now))
    sync.changed(
        MessagesUpdated(account_id, [message_id], {message_id: folder_of(now)})
    )


def _forgotten(sync: SyncService, account_id: str, message_id: str) -> None:
    """A message is gone for good: its id answers 404 from now on."""
    was = sync.folder_of(account_id, message_id)
    sync.forget(account_id, message_id)
    sync.changed(MessagesDeleted(account_id, [message_id], {message_id: was or ""}))
