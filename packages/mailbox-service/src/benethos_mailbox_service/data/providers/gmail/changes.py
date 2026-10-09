"""What the sync asks of an account: the folders, what is in them, and
what changed in one since a token (``DELTA``).

The token is Gmail's history id. ``history.list`` names every change of
the mailbox since then: a message added or deleted for good, labels put
on a message or taken off. Each folder reads them for itself: a message
that comes to carry the folder's label is changed there, one that loses
it is removed. "All Mail" holds what is neither in the trash nor in the
spam. Gmail keeps the history for about a week. An older id answers 404,
and the sync starts that folder afresh.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from ....errors import ChangesExpiredError, NotFoundError, ProviderError
from ..base import ChangedMessage, FolderChanges
from . import mappers, reading
from .api import GmailApi
from .shapes import GmailMessage, Histories, History, Profile


class Changes:
    def __init__(self, api: GmailApi, now: Callable[[], datetime]) -> None:
        self._api = api
        self._now = now

    async def folder_states(self) -> dict[str, str]:
        """Every folder, with the mailbox's history id: the sync of an
        adapter with ``DELTA`` asks each folder for its changes anyway."""
        state = await self._history_id()
        labels = await self._api.labels()
        return {f.id: state for f in mappers.folders(labels)}

    async def folder_contents(self, folder_id: str) -> list[str]:
        await reading.require_folder(self._api, folder_id)
        return await reading.ids(self._api, reading.folder_params(folder_id))

    async def message_headers(self, message_ids: list[str]) -> dict[str, str | None]:
        params = reading.metadata_params(("Message-ID",))
        found = await reading.messages(self._api, message_ids, params)
        return {
            i: next((h.value for h in m.payload.headers), None) if m.payload else None
            for i, m in found.items()
        }

    async def folder_changes(self, folder_id: str, token: str | None) -> FolderChanges:
        if token is None:
            start = await self._history_id()
            found = await self.folder_contents(folder_id)
            return FolderChanges(start, [ChangedMessage(i) for i in found])
        if not token.isdigit():
            raise ChangesExpiredError("not a gmail history id")
        records, latest = await self._history(token)
        changed, removed = _in_folder(folder_id, records, self._now())
        return FolderChanges(latest, changed, removed)

    async def _history_id(self) -> str:
        profile = await self._api.read(Profile, "GET", "/profile")
        if not profile.history_id:
            raise ProviderError("gmail named no history id")
        return profile.history_id

    async def _history(self, start: str) -> tuple[list[History], str]:
        """Every change since ``start``, and the history id now."""
        records: list[History] = []
        latest = start
        page_token: str | None = None
        while True:
            params = [
                ("startHistoryId", start),
                ("maxResults", str(reading.PAGE_SIZE)),
            ]
            if page_token:
                params.append(("pageToken", page_token))
            try:
                page = await self._api.read(Histories, "GET", "/history", params=params)
            except NotFoundError:
                raise ChangesExpiredError("gmail keeps no history this old") from None
            records += page.history
            latest = page.history_id or latest
            page_token = page.next_page_token
            if not page_token:
                return records, latest


def _in_folder(
    folder_id: str, records: list[History], now: datetime
) -> tuple[list[ChangedMessage], list[str]]:
    """What ``records`` changed in one folder, in their order: the last
    word on a message counts."""
    last: dict[str, bool] = {}  # id -> in the folder after the change
    added: set[str] = set()

    def inside(labels: set[str]) -> bool:
        return mappers.in_folder(folder_id, labels)

    for record in records:
        for item in record.messages_added:
            if inside(set(item.message.label_ids)):
                last[item.message.id] = True
                added.add(item.message.id)
        for item in record.messages_deleted:
            last[item.message.id] = False
        for change, put_on in (
            *((c, True) for c in record.labels_added),
            *((c, False) for c in record.labels_removed),
        ):
            _labelled(change.message, set(change.label_ids), put_on, inside, last)
    changed = [
        ChangedMessage(i, now if i in added else None)
        for i, there in last.items()
        if there
    ]
    removed = [i for i, there in last.items() if not there]
    return changed, removed


def _labelled(
    message: GmailMessage,
    labels: set[str],
    put_on: bool,
    inside: Callable[[set[str]], bool],
    last: dict[str, bool],
) -> None:
    """A change of labels: changed where the message is in the folder
    after it, removed where it was in before and is not after."""
    after = set(message.label_ids)
    before = after - labels if put_on else after | labels
    if inside(after):
        last[message.id] = True
    elif inside(before):
        last[message.id] = False
