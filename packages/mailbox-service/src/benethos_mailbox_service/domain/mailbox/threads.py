"""Threads of one account (CONCEPT 6.3): one with its messages, and the
messages of a folder by threads.

Gmail, JMAP and Microsoft keep threads themselves (``Threads``). For IMAP
the index keeps them (``sync``), and the messages are read by id
(``Summaries``). POP3 has none: ``501``. A grant that names folders sees
the messages of a thread in those folders only, and a thread without
one of them is not found.

A list of threads reads them all at once: for IMAP the summaries of
every thread on the page in one go, elsewhere a few threads at a time.
"""

from __future__ import annotations

from datetime import UTC, datetime

import anyio

from ...data.models import (
    Address,
    MessageSummary,
    Page,
    Thread,
    ThreadSummary,
)
from ...errors import MailboxServiceError, NotFoundError, missing
from ..accounts import summaries, threads
from ..rights import Access
from .calls import Calls, public
from .folders import Folders
from .reach import Reach, reach_of, require_folder

# The messages a thread lists at most, the newest.
THREAD_MESSAGES = 500
# Threads read from the provider at once, for a list of them.
AT_ONCE = 4

# The newest messages of each thread, oldest first, and whether it holds
# more, by thread.
Found = dict[str, tuple[list[MessageSummary], bool]]


class Threads:
    def __init__(
        self, calls: Calls, folders: Folders, limit: int = THREAD_MESSAGES
    ) -> None:
        self._calls = calls
        self._folders = folders
        self._limit = limit

    async def get_thread(
        self, access: Access, account_id: str, thread_id: str
    ) -> Thread:
        """The thread with the messages the caller may see, oldest first."""
        access.require("get_thread", account_id)
        reach = await reach_of(self._calls, access, "get_thread", account_id)
        thread = await self._visible(account_id, thread_id, reach)
        if thread is None:
            raise missing("thread", thread_id)
        return thread

    async def list_threads(
        self,
        access: Access,
        account_id: str,
        *,
        folder_id: str,
        limit: int,
        cursor: str | None,
    ) -> Page[ThreadSummary]:
        """The threads of a folder, newest first, each where its newest
        message in the folder is. A page is a page of the folder's
        messages, so it may hold fewer threads than ``limit``. ``folder_id``
        may also be a role such as ``inbox``."""
        access.require("list_threads", account_id)
        folder = await self._folders.by_role(account_id, folder_id) or folder_id
        reach = await reach_of(self._calls, access, "list_threads", account_id)
        if reach is not None:
            require_folder(reach, folder)
        page = await self._calls.call(
            account_id,
            lambda p: p.list_messages(folder, limit=limit, cursor=cursor),
        )
        listed = (await self._calls.published_page(account_id, page)).items
        ids = list(dict.fromkeys(m.thread_id for m in listed if m.thread_id))
        read = await self._read(account_id, ids)
        found: list[ThreadSummary] = []
        for thread_id in ids:
            thread = _visible(account_id, thread_id, read, reach)
            if thread is None or (cursor and _listed_before(thread, folder, listed)):
                continue
            found.append(
                ThreadSummary.model_validate(thread.model_dump(exclude={"messages"}))
            )
        return Page[ThreadSummary](items=found, next_cursor=page.next_cursor)

    async def _visible(
        self, account_id: str, thread_id: str, reach: Reach | None
    ) -> Thread | None:
        """The thread with the messages in reach, None without one."""
        if self._calls.keeps_threads(account_id):
            read = await self._from_index(account_id, [thread_id])
        else:
            read = {thread_id: await self._from_provider(account_id, thread_id)}
        return _visible(account_id, thread_id, read, reach)

    async def _read(self, account_id: str, thread_ids: list[str]) -> Found:
        """The newest messages of each thread of a list, some at once. A
        thread the provider no longer finds is left out."""
        if self._calls.keeps_threads(account_id):
            return await self._from_index(account_id, thread_ids)
        found: Found = {}
        failures: list[MailboxServiceError] = []
        limiter = anyio.CapacityLimiter(AT_ONCE)

        async def read(thread_id: str) -> None:
            async with limiter:
                if failures:
                    return
                try:
                    found[thread_id] = await self._from_provider(account_id, thread_id)
                except NotFoundError:
                    return
                except MailboxServiceError as exc:
                    failures.append(exc)

        async with anyio.create_task_group() as group:
            for thread_id in thread_ids:
                group.start_soon(read, thread_id)
        if failures:
            raise failures[0]
        return found

    async def _from_provider(
        self, account_id: str, thread_id: str
    ) -> tuple[list[MessageSummary], bool]:
        found = await self._calls.call(
            account_id, lambda p: threads(p).thread_messages(thread_id, self._limit)
        )
        published = await self._calls.published(account_id, found.messages)
        return published, found.truncated

    async def _from_index(self, account_id: str, thread_ids: list[str]) -> Found:
        """The messages the index names, read in one go, wherever they are."""
        entries = {t: self._calls.thread_entries(account_id, t) for t in thread_ids}
        wanted = {t: found[-self._limit :] for t, found in entries.items()}
        natives = [e.native_id for found in wanted.values() for e in found]
        read = (
            await self._calls.call(
                account_id, lambda p: summaries(p).summaries(natives)
            )
            if natives
            else {}
        )
        return {
            thread_id: (
                _oldest_first(
                    [
                        public(read[e.native_id], e.id, account_id, thread_id)
                        for e in found
                        if e.native_id in read
                    ]
                ),
                len(entries[thread_id]) > self._limit,
            )
            for thread_id, found in wanted.items()
        }


def _visible(
    account_id: str, thread_id: str, read: Found, reach: Reach | None
) -> Thread | None:
    """A thread read, with the messages in reach. None without one."""
    messages, truncated = read.get(thread_id, ([], False))
    if reach is not None:
        messages = [m for m in messages if reach.sees(m.folder_ids)]
    if not messages:
        return None
    return thread_of(thread_id, account_id, messages, truncated)


def thread_of(
    thread_id: str,
    account_id: str,
    messages: list[MessageSummary],
    truncated: bool = False,
) -> Thread:
    """A thread from its messages, oldest first."""
    newest = messages[-1]
    people: dict[str, Address] = {}
    for message in messages:
        for address in [*([message.sender] if message.sender else []), *message.to]:
            people.setdefault(address.email.lower(), address)
    return Thread(
        id=thread_id,
        account_id=account_id,
        subject=newest.subject,
        participants=list(people.values()),
        message_count=len(messages),
        unread_count=sum(1 for m in messages if m.unread),
        date=newest.date,
        snippet=newest.snippet,
        folder_ids=list(dict.fromkeys(f for m in messages for f in m.folder_ids)),
        truncated=truncated,
        messages=messages,
    )


def _oldest_first(messages: list[MessageSummary]) -> list[MessageSummary]:
    """By date, those without one last. The order they came stays among
    those of the same date."""
    return sorted(messages, key=lambda m: _when(m) or _LAST)


# After any date a message can carry.
_LAST = datetime.max.replace(tzinfo=UTC)


def _when(message: MessageSummary) -> datetime | None:
    """The date, in UTC where it names no zone."""
    date = message.date
    if date is None:
        return None
    return date if date.tzinfo else date.replace(tzinfo=UTC)


def _listed_before(thread: Thread, folder: str, listed: list[MessageSummary]) -> bool:
    """Whether a page before this one listed the thread: it has a message
    in the folder, not on this page, newer than the newest one here."""
    top = _when(listed[0]) if listed else None
    if top is None:
        return False
    here = {m.id for m in listed}
    return any(
        folder in m.folder_ids
        and m.id not in here
        and (when := _when(m)) is not None
        and when > top
        for m in thread.messages
    )
