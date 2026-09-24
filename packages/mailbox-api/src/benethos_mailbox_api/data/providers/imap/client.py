"""One IMAP session. The only module that imports ``imap_tools``.

Synchronous, like the library. The adapter runs it in a worker thread and
never calls it from two threads at once. Every library error leaves this
module as a ``MailboxApiError``.
"""

from __future__ import annotations

import imaplib
import ssl
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from imap_tools import (
    AND,
    ImapToolsError,
    MailBox,
    MailboxLoginError,
    MailBoxStartTls,
    MailMessage,
)

from ....errors import ProviderAuthError, ProviderError

MailBoxFactory = Callable[..., Any]


@dataclass(frozen=True)
class ImapServer:
    host: str
    port: int
    security: str  # "tls" or "starttls"


@dataclass(frozen=True)
class RawFolder:
    name: str
    delimiter: str | None
    flags: tuple[str, ...]


@dataclass(frozen=True)
class SearchCriteria:
    text: str | None = None
    unread: bool | None = None
    before_uid: int | None = None


def _default_mailbox(server: ImapServer, timeout: float) -> Any:
    context = ssl.create_default_context()
    if server.security == "starttls":
        return MailBoxStartTls(
            server.host, server.port, timeout=timeout, ssl_context=context
        )
    return MailBox(server.host, server.port, timeout=timeout, ssl_context=context)


class ImapSession:
    def __init__(
        self,
        server: ImapServer,
        timeout: float = 30.0,
        mailbox_factory: MailBoxFactory = _default_mailbox,
    ) -> None:
        self._server = server
        self._timeout = timeout
        self._factory = mailbox_factory
        self._mailbox: Any = None

    @property
    def connected(self) -> bool:
        return self._mailbox is not None

    def login(self, username: str, password: str) -> None:
        with _errors():
            mailbox = self._factory(self._server, self._timeout)
            try:
                mailbox.login(username, password, initial_folder=None)
            except MailboxLoginError:
                raise ProviderAuthError("the server rejected the login") from None
            self._mailbox = mailbox

    def login_oauth(self, username: str, access_token: str) -> None:
        with _errors():
            mailbox = self._factory(self._server, self._timeout)
            try:
                mailbox.xoauth2(username, access_token, initial_folder=None)
            except MailboxLoginError:
                raise ProviderAuthError("the server rejected the token") from None
            self._mailbox = mailbox

    def logout(self) -> None:
        mailbox, self._mailbox = self._mailbox, None
        if mailbox is not None:
            try:
                mailbox.logout()
            except (ImapToolsError, imaplib.IMAP4.error, OSError):
                pass

    def list_folders(self) -> list[RawFolder]:
        with _errors():
            return [
                RawFolder(f.name, f.delim, tuple(f.flags))
                for f in self._require().folder.list()
            ]

    def select(self, folder: str) -> int:
        """Select a folder read-only, return its UIDVALIDITY."""
        with _errors():
            mailbox = self._require()
            mailbox.folder.set(folder, readonly=True)
            status = mailbox.folder.status(folder, ["UIDVALIDITY"])
            return int(status["UIDVALIDITY"])

    def search(self, criteria: SearchCriteria) -> list[int]:
        """UIDs in the selected folder, ascending."""
        conditions: dict[str, Any] = {}
        if criteria.text:
            conditions["text"] = criteria.text
        if criteria.unread is not None:
            conditions["seen"] = not criteria.unread
        query: Any = AND(**conditions) if conditions else "ALL"
        charset = "UTF-8" if criteria.text and not criteria.text.isascii() else None
        with _errors():
            uids = [int(u) for u in self._require().uids(query, charset=charset)]
        uids.sort()
        if criteria.before_uid is not None:
            uids = [u for u in uids if u < criteria.before_uid]
        return uids

    def fetch_headers(self, uids: list[int]) -> list[MailMessage]:
        if not uids:
            return []
        with _errors():
            return list(
                self._require().fetch(
                    uid_list=[str(u) for u in uids],
                    headers_only=True,
                    mark_seen=False,
                    bulk=True,
                )
            )

    def fetch_message(self, uid: int) -> MailMessage | None:
        with _errors():
            found = list(self._require().fetch(uid_list=[str(uid)], mark_seen=False))
        return found[0] if found else None

    def fetch_raw(self, uid: int) -> bytes | None:
        with _errors():
            status, data = self._require().client.uid(
                "fetch", str(uid), "(BODY.PEEK[])"
            )
        if status != "OK":
            raise ProviderError("the server refused to hand out the message")
        for part in data:
            if isinstance(part, tuple) and len(part) == 2:
                return bytes(part[1])
        return None

    def _require(self) -> Any:
        if self._mailbox is None:
            raise ProviderError("not connected")
        return self._mailbox


@contextmanager
def _errors() -> Iterator[None]:
    try:
        yield
    except (ProviderAuthError, ProviderError):
        raise
    except TimeoutError:
        raise ProviderError("the mail server did not answer in time") from None
    except (ssl.SSLError, ssl.CertificateError) as exc:
        raise ProviderError(f"TLS with the mail server failed: {exc}") from None
    except (ImapToolsError, imaplib.IMAP4.error) as exc:
        raise ProviderError(f"the mail server answered with an error: {exc}") from None
    except OSError as exc:
        raise ProviderError(f"the mail server is not reachable: {exc}") from None
