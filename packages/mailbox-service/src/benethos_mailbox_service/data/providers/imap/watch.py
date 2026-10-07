"""Waiting for the server to report a change in the inbox: IDLE, over a
connection of its own, so requests are not held up."""

from __future__ import annotations

import threading
from collections.abc import Callable

import anyio

from ....errors import MailboxServiceError, NotSupportedError
from ...protocols import ImapSession
from ..guard import Guard
from . import mappers

# Threads waiting in IDLE, for adapters built without a limiter of the
# service's. The service passes one sized by its settings.
WATCHERS = anyio.CapacityLimiter(50)


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
