"""What the sync worker asks of an IMAP account: the state of each
folder, its contents, the headers that tie a message to its
conversation, with CONDSTORE which flags changed, each a sequence under
the adapter's lock. And waiting for the server to report a change in
the inbox: IDLE, over a connection of its own, so requests are not held
up."""

from __future__ import annotations

import threading
from collections.abc import Callable
from functools import partial
from typing import Protocol, TypeVar

import anyio

from ....common.chunks import batched
from ....errors import MailboxServiceError, NotSupportedError
from ...mail import ThreadHeaders
from ...protocols import ImapSession, SearchCriteria
from ..guard import Guard
from . import mappers
from .mailbox import Mailbox
from .messages import HEADER_BATCH, by_folder

T = TypeVar("T")

# Threads waiting in IDLE, for adapters built without a limiter of the
# service's. The service passes one sized by its settings.
WATCHERS = anyio.CapacityLimiter(50)


class Run(Protocol):
    """One step on the adapter's session, under its lock."""

    async def __call__(self, operation: Callable[[Mailbox], T]) -> T: ...


class ImapChanges:
    """The sync's questions, each a step the adapter runs (``run``), and
    the wait in IDLE."""

    def __init__(self, run: Run, idle: Idle) -> None:
        self._run = run
        self._idle = idle

    async def folder_states(self) -> dict[str, str]:
        return await self._run(_states)

    async def folder_contents(self, folder_id: str) -> list[str]:
        return await self._run(lambda box: _contents(box, folder_id))

    async def flag_changes(
        self, folder_id: str, since: str, message_ids: list[str]
    ) -> list[str]:
        return await self._run(lambda box: _flags(box, folder_id, since, message_ids))

    async def message_headers(self, message_ids: list[str]) -> dict[str, ThreadHeaders]:
        # Ids that are no id of this adapter are left out, like messages
        # that are gone.
        found: dict[str, ThreadHeaders] = {}
        for (folder, validity), by_uid in by_folder(message_ids)[0].items():
            # One request per batch, so a long first sync never holds the
            # connection for long.
            for batch in batched(list(by_uid), HEADER_BATCH):
                headers = partial(
                    _headers, folder=folder, validity=validity, uids=batch
                )
                found.update(await self._run(headers))
        return found

    async def wait_for_change(self, timeout: float) -> bool:
        return await self._idle.wait(timeout)


def _states(box: Mailbox) -> dict[str, str]:
    """``UIDVALIDITY.UIDNEXT.MESSAGES``, with CONDSTORE also
    ``.HIGHESTMODSEQ``, so that a flag change changes the state too."""
    modseq = "CONDSTORE" in box.session.server_capabilities()
    box.session.noop()
    states = {}
    for folder in box.list_folders():
        found = box.session.folders.folder_state(
            mappers.folder_name(folder.id), modseq=modseq
        )
        state = f"{found.uidvalidity}.{found.uidnext}.{found.messages}"
        highest = found.highest_modseq
        states[folder.id] = state if highest is None else f"{state}.{highest}"
    return states


def _flags(
    box: Mailbox, folder_id: str, since: str, message_ids: list[str]
) -> list[str]:
    """Only with CONDSTORE, and only while the folder keeps its UIDs."""
    parts = since.split(".")
    if len(parts) != 4 or not all(p.isdigit() for p in parts):
        return []
    folder = mappers.folder_name(folder_id)
    validity = int(parts[0])
    by_uid = by_folder(message_ids)[0].get((folder, validity), {})
    if not by_uid or box.session.select(folder) != validity:
        return []
    changed = box.session.messages.changed_since(sorted(by_uid), int(parts[3]))
    return [by_uid[uid] for uid in changed if uid in by_uid]


def _contents(box: Mailbox, folder_id: str) -> list[str]:
    folder = mappers.folder_name(folder_id)
    validity = box.session.select(folder)
    return [
        mappers.message_id(folder, validity, uid)
        for uid in box.session.messages.search(SearchCriteria())
    ]


def _headers(
    box: Mailbox, folder: str, validity: int, uids: list[int]
) -> dict[str, ThreadHeaders]:
    if box.session.select(folder) != validity:
        return {}  # renumbered: these ids are gone
    return {
        mappers.message_id(folder, validity, uid): headers
        for uid, headers in box.session.messages.fetch_thread_headers(uids).items()
    }


class Idle:
    def __init__(
        self,
        session: ImapSession,
        guard: Guard,
        login: Callable[[ImapSession], None],
        watchers: anyio.CapacityLimiter | None = None,
    ) -> None:
        """``watchers`` bounds the threads that wait in IDLE, shared by
        every adapter: without it a limiter of this module's own."""
        self._session = session
        self._guard = guard
        self._login = login
        self._watchers = watchers or WATCHERS
        self._lock = threading.Lock()
        self._closing = threading.Event()

    async def wait(self, timeout: float) -> bool:
        """True if the server reported a change within ``timeout``."""
        # A wait holds its thread for up to ``timeout``: never one of the
        # pool that answers requests and runs the other commands.
        return await anyio.to_thread.run_sync(
            self._wait,
            timeout,
            abandon_on_cancel=True,
            limiter=self._watchers,
        )

    def _wait(self, timeout: float) -> bool:
        with self._lock:
            if self._closing.is_set():
                return False
            self._guard.check()
            session = self._session
            try:
                with self._guard.refused_logins():
                    if not session.connected:
                        self._guard.acquire()
                        self._login(session)
                        if "IDLE" not in session.server_capabilities():
                            raise NotSupportedError(
                                "the mail server does not offer IDLE"
                            )
                        session.select(mappers.INBOX)
                    return session.idle(timeout, self._closing.is_set)
            except MailboxServiceError:
                session.logout()
                raise

    def closing(self) -> None:
        """A wait under way ends within ``IDLE_STEP``, none starts again."""
        self._closing.set()

    def close(self) -> None:
        """Waits for a running IDLE to notice ``closing``."""
        with self._lock:
            self._session.logout()
