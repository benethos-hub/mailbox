"""One POP3 session. The only module that imports ``poplib``.

Synchronous, like the library. The adapter runs it in a worker thread and
never calls it from two threads at once. Every library error leaves this
module as a ``MailboxServiceError``. This module only speaks the protocol:
message numbers, unique ids (UIDL) and bytes.

A POP3 session sees the mailbox as it was at the login, and the server
locks the mailbox for as long as it lasts. Deletions take effect at QUIT.
The adapter therefore opens a session per step and ends it at once.
"""

from __future__ import annotations

import poplib
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from ...common.sizes import MIB
from ...errors import (
    BadRequestError,
    NotSupportedError,
    ProviderAuthError,
    ProviderError,
    ProviderUnavailableError,
)
from .transport import Server, names, one_line, text, transport_errors

ConnectionFactory = Callable[[Server, float], Any]

DEFAULT_PORTS = {"tls": 995, "starttls": 110}

# A whole message larger than this is refused, as IMAP does.
MAX_MESSAGE_BYTES = 40 * MIB

# poplib refuses a line longer than 2048 bytes. Mail breaks that limit of
# RFC 5322 often enough, e.g. HTML in one line, and IMAP reads it. A
# message is held to MAX_MESSAGE_BYTES as a whole before it is read.
_LONGEST_LINE = max(getattr(poplib, "_MAXLINE", 2048), MAX_MESSAGE_BYTES)
poplib._MAXLINE = _LONGEST_LINE  # type: ignore[attr-defined]


def _default_connection(server: Server, timeout: float) -> Any:
    address, context = server.endpoint()
    if server.security == "tls":
        return poplib.POP3_SSL(address, server.port, timeout=timeout, context=context)
    connection = poplib.POP3(address, server.port, timeout=timeout)
    try:
        connection.stls(context=context)
    except BaseException:
        _quietly_close(connection)
        raise
    return connection


class Pop3Session:
    def __init__(
        self,
        server: Server,
        timeout: float = 30.0,
        connection_factory: ConnectionFactory = _default_connection,
        max_bytes: int = MAX_MESSAGE_BYTES,
    ) -> None:
        self._server = server
        self._timeout = timeout
        self._factory = connection_factory
        self._max_bytes = max_bytes
        self._connection: Any = None

    def read_capabilities(self) -> frozenset[str]:
        """Connect without logging in and return what the server announces
        after TLS or STLS (CAPA, RFC 2449). Sends no credential."""
        with _errors():
            connection = self._factory(self._server, self._timeout)
            try:
                return _capabilities(connection)
            finally:
                _quietly_quit(connection)

    def login(self, username: str, password: str) -> None:
        """USER and PASS. Raises ``ProviderAuthError`` if the server rejects
        the credential."""
        one_line(username, password, what="the user name or password")
        with _errors():
            connection = self._factory(self._server, self._timeout)
            try:
                connection.user(username)
                connection.pass_(password)
            except poplib.error_proto as exc:
                _quietly_close(connection)
                refusal = _text(exc)
                if _for_now(refusal):
                    raise ProviderUnavailableError(
                        "the mail server refused the login for now"
                    ) from None
                raise ProviderAuthError("the server rejected the login") from None
            except BaseException:
                _quietly_close(connection)
                raise
            self._connection = connection

    def unique_ids(self) -> list[tuple[int, str]]:
        """Message number and unique id (UIDL) of every message, oldest
        first. A server without UIDL is refused: without it no id of a
        message survives the session."""
        with _errors():
            try:
                _, lines, _ = self._require().uidl()
            except poplib.error_proto:
                raise NotSupportedError(
                    "the mail server offers no UIDL: its messages have no lasting ids"
                ) from None
        found = []
        for line in lines:
            number, _, uid = _text(line).partition(" ")
            if number.isdigit() and uid:
                found.append((int(number), uid.strip()))
        return found

    def headers(self, number: int) -> bytes:
        """The header of one message (TOP n 0). Without TOP, the whole
        message, of which the reader takes the header."""
        with _errors():
            connection = self._require()
            try:
                _, lines, _ = connection.top(number, 0)
            except poplib.error_proto:
                if "TOP" in _capabilities(connection):
                    raise
                return self.message(number)
        return b"\r\n".join(lines) + b"\r\n"

    def message(self, number: int) -> bytes:
        """The whole message (RETR). Refused when it is larger than allowed."""
        with _errors():
            connection = self._require()
            size = _size(connection, number)
            if size > self._max_bytes:
                raise ProviderError(
                    f"message {number} is larger than {self._max_bytes} bytes"
                )
            _, lines, _ = connection.retr(number)
        return b"\r\n".join(lines) + b"\r\n"

    def delete(self, number: int) -> None:
        """Mark a message deleted (DELE). It goes at ``commit``."""
        with _errors():
            self._require().dele(number)

    def commit(self) -> None:
        """QUIT: the deletions take effect, the session ends. A server that
        does not confirm keeps the messages."""
        connection, self._connection = self._connection, None
        if connection is None:
            return
        with _errors():
            try:
                connection.quit()
            except poplib.error_proto as exc:
                _quietly_close(connection)
                raise ProviderError(
                    f"the mail server did not finish the session: {_text(exc)}"
                ) from None

    def logout(self) -> None:
        """End the session. Deletions not yet committed are dropped where
        the server allows (RSET), else they take effect as at QUIT."""
        connection, self._connection = self._connection, None
        if connection is None:
            return
        try:
            connection.rset()
        except (poplib.error_proto, OSError):
            pass
        _quietly_quit(connection)

    def _require(self) -> Any:
        if self._connection is None:
            raise ProviderUnavailableError("not connected to the mail server")
        return self._connection


def _size(connection: Any, number: int) -> int:
    """LIST n: the size of one message in bytes."""
    answer = _text(connection.list(number))
    parts = answer.split()
    if len(parts) >= 3 and parts[2].isdigit():
        return int(parts[2])
    return 0


def _capabilities(connection: Any) -> frozenset[str]:
    """The names of what CAPA lists, upper case. Empty for a server without
    CAPA."""
    try:
        return names(connection.capa())
    except poplib.error_proto:
        return frozenset()


def _text(value: Any) -> str:
    """A line of the server, or the one a refusal carries, as text."""
    if isinstance(value, poplib.error_proto):
        value = value.args[0] if value.args else ""
    return text(value) if isinstance(value, bytes | str) else str(value)


# RFC 2449 and RFC 3206 response codes. [AUTH] says the credential is wrong,
# the others that the server cannot take a login now. A refusal without a
# code counts as a rejected credential, as most servers answer a wrong
# password so.
_FOR_NOW = ("[IN-USE]", "[LOGIN-DELAY]", "[SYS/TEMP]")
_FOR_NOW_TEXT = re.compile(r"too many|try again later|locked", re.IGNORECASE)


def _for_now(refusal: str) -> bool:
    """Whether the server's refusal of a login is temporary."""
    upper = refusal.upper()
    if "[AUTH]" in upper or "[SYS/PERM]" in upper:
        return False
    return any(code in upper for code in _FOR_NOW) or bool(
        _FOR_NOW_TEXT.search(refusal)
    )


def _quietly_quit(connection: Any) -> None:
    try:
        connection.quit()
    except (poplib.error_proto, OSError):
        _quietly_close(connection)


def _quietly_close(connection: Any) -> None:
    try:
        connection.close()
    except OSError:
        pass


@contextmanager
def _errors() -> Iterator[None]:
    with transport_errors():
        try:
            yield
        except (
            BadRequestError,
            NotSupportedError,
            ProviderAuthError,
            ProviderError,
            ProviderUnavailableError,
        ):
            raise
        except poplib.error_proto as exc:
            raise ProviderError(
                f"the mail server answered with an error: {_text(exc)}"
            ) from None
