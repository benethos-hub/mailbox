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

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

import anyio

from ...data.models import (
    Address,
    MessageSummary,
    Page,
    Thread,
    ThreadSummary,
    received_or_written,
)
from ...data.providers import Reads
from ...errors import MailboxServiceError, NotFoundError, missing
from .. import paging
from ..accounts import NEEDS, summaries, threads
from ..rights import Access
from .calls import Calls, public
from .folders import Folders, holder
from .reach import Reach, reach_of, require_folder

# The messages a thread lists at most, the newest.
THREAD_MESSAGES = 500
# Threads read from the provider at once, for a list of them.
AT_ONCE = 4

_CURSOR_PREFIX = "t_"

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
        await self._calls.require(account_id, NEEDS["get_thread"])
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
        message in the folder is, with that message's subject, date and
        snippet. A page is a page of the folder's
        messages, so it may hold fewer threads than ``limit``. ``folder_id``
        may also be a role such as ``inbox``."""
        access.require("list_threads", account_id)
        await self._calls.require(account_id, NEEDS["list_threads"])
        folder = await self._folders.by_role(account_id, folder_id) or folder_id
        reach = await reach_of(self._calls, access, "list_threads", account_id)
        if reach is not None:
            require_folder(reach, folder)
        keeps = self._calls.keeps_threads(account_id)
        before = _Before.of(cursor)
        page = await self._calls.call(
            account_id,
            lambda p: _threaded(p, keeps).list_messages(
                folder, limit=limit, cursor=before.cursor if before else None
            ),
        )
        listed = (await self._calls.published_page(account_id, page)).items
        ids = list(dict.fromkeys(m.thread_id for m in listed if m.thread_id))
        own = self._calls.record(account_id).email
        read = await self._read(account_id, ids)
        holds = holder(await self._folders.all(account_id), folder)
        found: list[ThreadSummary] = []
        for thread_id in ids:
            thread = _visible(account_id, thread_id, read, reach, own)
            if thread is None or (before and before.listed(thread, holds, listed)):
                continue
            # Its row shows the newest message in the folder, where it stands.
            here = next(m for m in listed if m.thread_id == thread_id)
            found.append(
                ThreadSummary.model_validate(
                    {
                        **thread.model_dump(exclude={"messages"}),
                        "subject": here.subject,
                        "date": here.date,
                        "snippet": here.snippet,
                    }
                )
            )
        return Page[ThreadSummary](
            items=found, next_cursor=_Before.after(page.next_cursor, listed)
        )

    async def _visible(
        self, account_id: str, thread_id: str, reach: Reach | None
    ) -> Thread | None:
        """The thread with the messages in reach, None without one."""
        if self._calls.keeps_threads(account_id):
            read = await self._from_index(account_id, [thread_id])
        else:
            read = {thread_id: await self._from_provider(account_id, thread_id)}
        own = self._calls.record(account_id).email
        return _visible(account_id, thread_id, read, reach, own)

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


def _threaded(adapter: Reads, keeps: bool) -> Reads:
    """The adapter of an account with threads, kept by the index or by the
    provider. Without them: ``501``, before anything is listed."""
    if not keeps:
        threads(adapter)
    return adapter


def _visible(
    account_id: str, thread_id: str, read: Found, reach: Reach | None, own: str
) -> Thread | None:
    """A thread read, with the messages in reach. None without one."""
    messages, truncated = read.get(thread_id, ([], False))
    if reach is not None:
        messages = [m for m in messages if reach.sees(m.folder_ids)]
    if not messages:
        return None
    return thread_of(thread_id, account_id, messages, truncated, own)


def thread_of(
    thread_id: str,
    account_id: str,
    messages: list[MessageSummary],
    truncated: bool = False,
    own: str | None = None,
) -> Thread:
    """A thread from its messages, oldest first. Its participants leave
    out the account's ``own`` address, unless nobody else took part."""
    newest = messages[-1]
    people: dict[str, Address] = {}
    for message in messages:
        for address in [*([message.sender] if message.sender else []), *message.to]:
            people.setdefault(address.email.lower(), address)
    others = {k: a for k, a in people.items() if k != (own or "").lower()}
    people = others or people
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
    """By when they came, those without a time last. The order they came stays among
    those of the same date."""
    return sorted(messages, key=lambda m: _when(m) or _LAST)


# After any date a message can carry.
_LAST = datetime.max.replace(tzinfo=UTC)


def _when(message: MessageSummary) -> datetime | None:
    """When it came, in UTC where it names no zone."""
    date = received_or_written(message)
    if date is None:
        return None
    return date if date.tzinfo else date.replace(tzinfo=UTC)


@dataclass(frozen=True)
class _Before:
    """What a cursor of a list of threads carries: the cursor of the
    folder's messages, and the messages of the page before that came in
    its last second. One of them may share that second with this page."""

    cursor: str
    last: frozenset[str]

    @classmethod
    def of(cls, cursor: str | None) -> _Before | None:
        if cursor is None:
            return None
        return paging.decode_cursor(
            _CURSOR_PREFIX, cursor, lambda c: cls(str(c[0]), frozenset(map(str, c[1])))
        )

    @staticmethod
    def after(cursor: str | None, listed: list[MessageSummary]) -> str | None:
        """The cursor of the next page, after ``listed``."""
        if cursor is None:
            return None
        times = [when for m in listed if (when := _when(m)) is not None]
        last = [m.id for m in listed if times and _when(m) == min(times)]
        return paging.encode_cursor(_CURSOR_PREFIX, [cursor, last])

    def listed(
        self,
        thread: Thread,
        holds: Callable[[Iterable[str]], bool],
        listed: list[MessageSummary],
    ) -> bool:
        """Whether a page before this one listed the thread: it has a
        message in the folder, not on this page, newer than the newest one
        here or listed in the last second of the page before."""
        top = _when(listed[0]) if listed else None
        if top is None:
            return False
        here = {m.id for m in listed}
        return any(
            holds(m.folder_ids)
            and m.id not in here
            and (m.id in self.last or ((when := _when(m)) is not None and when > top))
            for m in thread.messages
        )
