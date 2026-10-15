"""What the adapters that log in to a mail server share, IMAP and POP3:
the settings of the login, the guard towards the server, sending through
the account's SMTP server, and the steps of one session under one lock,
in a worker thread. Before an account exists: its settings from
discovered servers, and a probe of a server without a login.

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
from ...errors import BadRequestError, NotSupportedError
from ..models import MailServer
from ..protocols import Pick, Server, SmtpSession
from .base import CredentialReader, ProviderSettings
from .guard import Guard, Pace
from .sender import SmtpFactory, SmtpSender, smtp_settings
from .settings import mail_server, rate_of

T = TypeVar("T")
A = TypeVar("A")

# A probe asks a server what it offers before anyone logs in, and does not
# wait long for the answer.
PROBE_TIMEOUT = 10.0


class Probed(Protocol):
    """A session that reads what its server offers without a login."""

    def read_capabilities(self) -> frozenset[str]: ...


def login_settings(
    server: MailServer, servers: list[MailServer], email: str
) -> dict[str, str | int | bool]:
    """The settings of a login at a discovered ``server``, with the SMTP
    server of ``servers`` to send through."""
    username = server.username or email
    return {
        "host": server.host,
        "port": server.port,
        "security": str(server.security),
        "username": username,
        **smtp_settings(servers, username),
    }


async def capabilities_of(
    session_factory: Callable[[Server], Probed],
    protocol: str,
    ports: Mapping[str, int],
    host: str,
    port: int,
    security: str,
    address: str | None,
) -> frozenset[str]:
    """The capabilities of a ``protocol`` server, read without logging in.
    With ``address``, the connection goes there, the address just checked."""
    if security not in ports:
        raise BadRequestError(f"{protocol} without encryption is not supported")
    pick = (lambda _host, _port: address) if address is not None else None
    session = session_factory(
        Server(host=host, port=port, security=security, pick=pick)
    )
    return await anyio.to_thread.run_sync(session.read_capabilities)


class MailServerAdapter:
    """The base of the IMAP and POP3 adapters. A subclass names its
    ``protocol``, an ``account`` of it and the default ``ports``, and
    checks ``auth`` in ``_check_auth``."""

    protocol = ""
    account = ""
    ports: Mapping[str, int] = {}

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
            raise NotSupportedError(
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
