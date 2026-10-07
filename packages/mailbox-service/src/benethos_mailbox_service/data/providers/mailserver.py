"""What the adapters that log in to a mail server share, IMAP and POP3:
the settings of the login, the guard towards the server, sending through
the account's SMTP server, and the steps of one session under one lock,
in a worker thread.

Their libraries are synchronous and their sessions stateful, so a step
runs as one uninterrupted sequence under the account's lock. The
credential is decrypted right before a login and not kept.
"""

from __future__ import annotations

import itertools
import threading
import time
from collections.abc import Callable, Mapping
from typing import Protocol, TypeVar

import anyio

from ...common.ratelimit import Clock, Sleep
from ...errors import BadRequestError, ConflictError
from ..protocols import Pick, Server, SmtpSession
from .base import Capability, CredentialReader, ProviderSettings
from .guard import Guard, Pace
from .sender import SmtpFactory, SmtpSender
from .settings import mail_server, rate_of

T = TypeVar("T")
A = TypeVar("A")


class MailServerAdapter:
    """The base of the IMAP and POP3 adapters. A subclass names its
    ``protocol``, an ``account`` of it and the default ``ports``, and
    checks ``auth`` in ``_check_auth``."""

    protocol = ""
    account = ""
    ports: Mapping[str, int] = {}
    capabilities: frozenset[Capability] = frozenset()

    def __init__(
        self,
        settings: ProviderSettings,
        credentials: CredentialReader,
        *,
        clock: Clock = time.monotonic,
        sleep: Sleep = time.sleep,
        jitter: Callable[[float, float], float] | None = None,
        smtp_factory: SmtpFactory = SmtpSession,
        pick: Pick | None = None,
        pace: Pace | None = None,
    ) -> None:
        """``pick`` checks the host of each connection, to the mail server
        and to SMTP. ``pace`` is how fast steps go, unless the settings
        name a rate."""
        login = mail_server(settings, self.account, self.protocol, self.ports)
        self._check_auth(str(settings.get("auth", "password")))
        self._server = Server(
            host=login.host, port=login.port, security=login.security, pick=pick
        )
        self._username = login.username
        self._credentials = credentials
        pace = pace or Pace()
        self._guard = Guard(
            rate_of(settings, "max_requests_per_minute", pace.per_minute),
            pace.burst,
            clock=clock,
            sleep=sleep,
            jitter=jitter,
            attempts=pace.attempts,
            first_pause=pace.first_pause,
            longest_pause=pace.longest_pause,
            name=f"requests to {login.host}",
        )
        self._smtp = SmtpSender.from_settings(
            settings,
            self._username,
            "password",
            self._secret,
            self._guard,
            smtp_factory,
            pick,
        )
        if self._smtp is not None:
            self.capabilities = self.capabilities | {Capability.SEND}
        self._lock = threading.Lock()

    def _check_auth(self, auth: str) -> None:
        if auth != "password":
            raise BadRequestError("settings.auth must be 'password'")

    async def _send_smtp(
        self, raw: bytes, sender: str, recipients: list[str]
    ) -> list[str]:
        """Send through the account's SMTP server. The recipients it
        refused."""
        if self._smtp is None:
            raise ConflictError(
                "the account has no SMTP server: its settings name no smtp_host"
            )
        return await anyio.to_thread.run_sync(self._smtp.send, raw, sender, recipients)

    async def _in_thread(self, step: Callable[[], T]) -> T:
        """``step`` in a worker thread."""
        return await anyio.to_thread.run_sync(step)

    def _attempted(self, session: Session, step: Callable[[], T]) -> T:
        """``step`` under the lock, through the guard: tried again while
        the server does not answer, the session dropped before each try."""
        with self._lock:
            return self._guard.attempts(step, drop=session.logout)

    def _verified(self, session: Session, check: Callable[[], None]) -> None:
        """A login checked afresh by ``check``, an earlier rejected login
        forgotten first, then the SMTP server's."""
        with self._lock:
            self._guard.reset()
            session.logout()
            with self._guard.refused_logins():
                check()
                if self._smtp is not None:
                    self._smtp.verify()

    def _closed(self, session: Session) -> None:
        with self._lock:
            session.logout()

    def _login(self, session: Session) -> None:
        session.login(self._username, self._secret())

    def _secret(self) -> str:
        """The credential for the login, decrypted for this one use."""
        return self._credentials("password").get_secret_value()

    @staticmethod
    def _counting(operation: Callable[[A, bool], T]) -> Callable[[A], T]:
        """``operation`` as a step the guard may run again. It learns
        whether this is a retry, so that finding its work done counts as
        done, not as a conflict or a missing item."""
        attempts = itertools.count()
        return lambda value: operation(value, next(attempts) > 0)


class Session(Protocol):
    """What the base needs of a session: a login and a logout."""

    def login(self, username: str, password: str) -> None: ...

    def logout(self) -> None: ...
