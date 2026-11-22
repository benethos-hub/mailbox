"""The open items of an agent, kept in its state file."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime

from ..records import MessageRef, OpenItem
from ..store import Store

__all__ = ["StoredItems"]


class StoredItems:
    """:class:`~benethos_mailbox_agents.contract.Items` over a state file."""

    def __init__(
        self,
        store: Store,
        now: Callable[[], datetime],
        stage: str | None = None,
    ) -> None:
        self._store = store
        self._now = now
        self._stage = stage

    async def open(self, ref: MessageRef, thread_id: str | None, due: datetime) -> None:
        self._store.open_item(ref, thread_id, due, self._now())

    async def restart(self, ref: MessageRef, due: datetime) -> None:
        self._store.restart_item(ref, due, self._now())

    async def get(self, ref: MessageRef) -> OpenItem | None:
        return self._store.item(ref)

    async def in_thread(self, account_id: str, thread_id: str) -> list[OpenItem]:
        return self._store.items_in_thread(account_id, thread_id)

    async def due(self, now: datetime) -> list[OpenItem]:
        return self._store.due_items(now, self._stage)

    async def close(self, ref: MessageRef, reason: str) -> None:
        self._store.close_item(ref, reason, self._now())

    async def marked_closed(self, reasons: Sequence[str]) -> list[OpenItem]:
        return self._store.marked_closed_items(reasons)
