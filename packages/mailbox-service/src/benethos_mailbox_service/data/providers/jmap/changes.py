"""What the sync worker asks of a JMAP account: the folders' counts,
their contents, the Message-ID headers, what changed since a state
(``DELTA``) and, from the event source, that something did (``PUSH``).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

import anyio

from ....errors import ProviderUnavailableError, missing
from ...protocols import jmap
from ..base import ChangedMessage, FolderChanges
from . import mappers
from .account import JmapAccount

# Message ids asked for at once while listing a whole folder.
QUERY_PAGE = 500
# Changes asked for at once (Email/changes).
MAX_CHANGES = 500
# The seconds between the pings of the event source, and how long a read
# waits for the next line before the stream counts as broken.
PING = 60
PING_WAIT = 2 * PING + 30


@dataclass(frozen=True)
class Since:
    """What changed in the account since a state: where each created or
    changed message is now, and which are gone."""

    state: str
    where: dict[str, frozenset[str]] = field(default_factory=dict)
    created: frozenset[str] = frozenset()
    destroyed: tuple[str, ...] = ()
    at: datetime | None = None


class Changes:
    """The changes of one account, and the states it saw last."""

    def __init__(self, account: JmapAccount, now: Callable[[], datetime]) -> None:
        self._account = account
        self._now = now
        # The changes since one state, asked once for every folder of a pass.
        self._since: tuple[str, Since] | None = None
        # The state of the account's emails the push last saw.
        self._pushed: str | None = None

    def forget(self) -> None:
        """A fresh start, e.g. after a new login."""
        self._since = None

    async def folder_states(self) -> dict[str, str]:
        """The counts stand in for a state. The sync asks every folder what
        changed since the account's state, whatever these say."""
        return {
            str(m["id"]): f"{m.get('totalEmails')}.{m.get('unreadEmails')}"
            for m in await self._account.mailboxes()
        }

    async def folder_contents(self, folder_id: str) -> list[str]:
        if not mappers.is_id(folder_id):
            raise missing("folder", folder_id)
        _, ids = await self._contents(folder_id)
        return ids

    async def message_headers(self, message_ids: list[str]) -> dict[str, str | None]:
        found = await self._account.emails(message_ids, ["messageId"])
        return {
            message_id: f"<{email['messageId'][0]}>" if email.get("messageId") else None
            for message_id, email in found.items()
        }

    async def folder_changes(self, folder_id: str, token: str | None) -> FolderChanges:
        """The token is the state of the account's emails. JMAP tells what
        changed in the account, not in a folder: a message counts as changed
        in the folder it is in now and as removed from every other one, so a
        move shows as one. A deleted message is removed from every folder."""
        if not mappers.is_id(folder_id):
            raise missing("folder", folder_id)
        if token is None:
            state, ids = await self._contents(folder_id)
            return FolderChanges(state, [ChangedMessage(i) for i in ids])
        changes = await self._changes(token)
        changed: list[ChangedMessage] = []
        removed = list(changes.destroyed)
        for message_id, folders in changes.where.items():
            if folder_id in folders:
                created = changes.at if message_id in changes.created else None
                changed.append(ChangedMessage(message_id, created))
            elif message_id not in changes.created:
                removed.append(message_id)
        return FolderChanges(changes.state, changed, removed)

    async def wait_for_change(self, timeout: float) -> bool:
        """The event source, until the state of the account's emails moves
        on from the one the last wait saw."""
        owner = await self._account.id()
        found = await self._account.one("Email/get", {"ids": []})
        state = str(found.get("state") or "")
        if self._pushed is not None and state != self._pushed:
            self._pushed = state
            return True
        self._pushed = state
        with anyio.move_on_after(timeout):
            async with self._account.client.events("Email", PING, PING_WAIT) as stream:
                async for changed in stream:
                    now = (changed.get(owner) or {}).get("Email")
                    if now and now != self._pushed:
                        self._pushed = str(now)
                        return True
            raise ProviderUnavailableError("the JMAP server closed its event stream")
        return False

    async def _contents(self, folder_id: str) -> tuple[str, list[str]]:
        """The state of the account's emails, then the ids of every message
        in the folder. The state is read first: a message that arrives while
        the folder is read counts again with the next changes."""
        owner = await self._account.id()
        query = {
            "accountId": owner,
            "filter": {"inMailbox": folder_id},
            "sort": mappers.SORT,
            "limit": QUERY_PAGE,
        }
        answers = await self._account.call(
            ("Email/get", {"accountId": owner, "ids": []}, "s"),
            ("Email/query", {**query, "position": 0}, "q"),
        )
        state = str(jmap.result(answers, "s").get("state") or "")
        ids: list[str] = []
        page = jmap.result(answers, "q")
        while True:
            found = [str(i) for i in page.get("ids") or []]
            ids += found
            if not found or (len(found) < QUERY_PAGE and "limit" not in page):
                return state, ids
            page = await self._account.one(
                "Email/query", {**query, "position": len(ids)}
            )

    async def _changes(self, token: str) -> Since:
        """What changed since ``token``, asked once for all folders of a
        pass: each asks with the same token."""
        if self._since is not None and self._since[0] == token:
            return self._since[1]
        created: set[str] = set()
        updated: set[str] = set()
        destroyed: set[str] = set()
        state = token
        while True:
            found = await self._account.one(
                "Email/changes", {"sinceState": state, "maxChanges": MAX_CHANGES}
            )
            created |= {str(i) for i in found.get("created") or []}
            updated |= {str(i) for i in found.get("updated") or []}
            destroyed |= {str(i) for i in found.get("destroyed") or []}
            state = str(found.get("newState") or state)
            if not found.get("hasMoreChanges"):
                break
        # Created and gone again within the span: nothing to report.
        fleeting = created & destroyed
        destroyed -= fleeting
        where = await self._account.emails(
            sorted((created | updated) - destroyed - fleeting), ["mailboxIds"]
        )
        gone = (created | updated) - destroyed - fleeting - set(where)
        result = Since(
            state=state,
            where={i: frozenset(e.get("mailboxIds") or {}) for i, e in where.items()},
            # JMAP says which are new since the token. They count as created
            # now, the moment the sync learns of them.
            created=frozenset(created - fleeting),
            destroyed=tuple(sorted(destroyed | (gone - created))),
            at=self._now(),
        )
        self._since = (token, result)
        return result
