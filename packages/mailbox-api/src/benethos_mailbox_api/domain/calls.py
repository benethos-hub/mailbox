"""Provider calls under our stable message ids.

Callers name messages by our ids (``sync``), providers by their own. This
module translates between the two, follows a message another client moved,
and keeps the account's status in step with how each call went. It checks
no rights: the services that use it do.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from ..data.models import MessageSummary, MessageUpdate
from ..data.providers import MailProvider
from ..errors import MailboxApiError, NotFoundError
from .accounts import AccountService
from .sync import SyncService

T = TypeVar("T")
S = TypeVar("S", bound=MessageSummary)


class Calls:
    def __init__(self, accounts: AccountService, sync: SyncService) -> None:
        self.accounts = accounts
        self.sync = sync

    async def call(
        self, account_id: str, operation: Callable[[MailProvider], Awaitable[T]]
    ) -> T:
        """Run one provider operation and keep the account's status in step
        with how it went."""
        return await self.accounts.observe(
            account_id, operation(self.accounts.provider(account_id))
        )

    async def on_message(
        self,
        account_id: str,
        message_id: str,
        operation: Callable[[MailProvider, str], Awaitable[T]],
    ) -> T:
        """Run an operation on the message behind one of our ids."""
        return await self.sync.resolve(
            account_id,
            message_id,
            lambda native: self.call(account_id, lambda p: operation(p, native)),
        )

    async def published(
        self, account_id: str, items: list[MessageSummary]
    ) -> list[MessageSummary]:
        """The provider's summaries with our ids and the account."""
        ids = await self.sync.public_ids(
            account_id, [(i.id, folder_of(i)) for i in items]
        )
        return [
            public(item, our_id, account_id)
            for item, our_id in zip(items, ids, strict=True)
        ]

    async def update(
        self, account_id: str, ids: list[str], changes: MessageUpdate
    ) -> dict[str, MessageSummary | MailboxApiError]:
        """Change messages; the outcome per id."""
        outcomes, natives = await self._on_messages(
            account_id, ids, lambda p, n: p.update_messages(n, changes)
        )
        results: dict[str, MessageSummary | MailboxApiError] = {}
        for message_id, outcome in outcomes.items():
            if isinstance(outcome, MailboxApiError):
                results[message_id] = outcome
                continue
            self.follow(account_id, message_id, natives[message_id], outcome)
            results[message_id] = public(outcome, message_id, account_id)
        return results

    async def delete(
        self, account_id: str, ids: list[str], permanent: bool
    ) -> dict[str, None | MailboxApiError]:
        """Into the trash, or for good; the outcome per id."""
        outcomes, natives = await self._on_messages(
            account_id, ids, lambda p, n: p.delete_messages(n, permanent)
        )
        results: dict[str, None | MailboxApiError] = {}
        for message_id, outcome in outcomes.items():
            if isinstance(outcome, MailboxApiError):
                results[message_id] = outcome
                continue
            if permanent:
                self.sync.forget(account_id, message_id)
            elif outcome is not None:
                self.follow(account_id, message_id, natives[message_id], outcome)
            results[message_id] = None
        return results

    def follow(
        self, account_id: str, message_id: str, native: str, now: MessageSummary
    ) -> None:
        """A message the provider moved: its id points to the new place."""
        if now.id != native:
            self.sync.relocate(account_id, message_id, now.id, folder_of(now))

    async def _on_messages(
        self,
        account_id: str,
        ids: list[str],
        run: Callable[[MailProvider, list[str]], Awaitable[dict[str, Any]]],
    ) -> tuple[dict[str, Any], dict[str, str]]:
        """Run a provider operation on the messages behind ``ids``. Those
        the provider does not find where the index says get one sync and a
        second try. Returns the outcome per id and the provider id used."""
        natives = {i: n for i, n in self.sync.natives(account_id, ids).items() if n}
        outcomes: dict[str, Any] = {
            i: NotFoundError(f"message {i} not found") for i in ids if i not in natives
        }
        outcomes.update(await self._run_on(account_id, natives, run))
        missing = [i for i in natives if isinstance(outcomes[i], NotFoundError)]
        if missing and self.sync.mapped(account_id):
            await self.sync.sync_account(account_id)
            moved = {
                i: n
                for i, n in self.sync.natives(account_id, missing).items()
                if n and n != natives[i]
            }
            outcomes.update(await self._run_on(account_id, moved, run))
            natives.update(moved)
        for message_id, outcome in outcomes.items():
            if isinstance(outcome, NotFoundError):
                outcomes[message_id] = NotFoundError(f"message {message_id} not found")
        return outcomes, natives

    async def _run_on(
        self,
        account_id: str,
        natives: dict[str, str],
        run: Callable[[MailProvider, list[str]], Awaitable[dict[str, Any]]],
    ) -> dict[str, Any]:
        if not natives:
            return {}
        by_native = await self.call(
            account_id, lambda p: run(p, list(natives.values()))
        )
        missing = NotFoundError("message not found")
        return {i: by_native.get(n, missing) for i, n in natives.items()}


def folder_of(message: MessageSummary) -> str:
    """The provider's folder of a message, empty where it names none."""
    return message.folder_ids[0] if message.folder_ids else ""


def public(message: S, message_id: str, account_id: str) -> S:
    """A provider's message under our id, with its account."""
    return message.model_copy(update={"id": message_id, "account_id": account_id})
