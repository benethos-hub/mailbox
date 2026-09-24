"""One IMAP session. The only module that imports ``imap_tools``.

Synchronous, like the library. The adapter runs it in a worker thread and
never calls it from two threads at once. Every library error leaves this
module as a ``MailboxApiError``.
"""

from __future__ import annotations

import imaplib
import re
import ssl
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from email.parser import BytesHeaderParser
from typing import Any

from imap_tools import (
    AND,
    ImapToolsError,
    MailBox,
    MailboxLoginError,
    MailBoxStartTls,
    MailMessage,
)

from ....errors import ProviderAuthError, ProviderError, ProviderUnavailableError

MailBoxFactory = Callable[..., Any]

# How often a waiting IDLE looks whether it should stop. Costs no traffic.
IDLE_STEP = 5.0


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
        client_id: tuple[str, str] | None = None,
    ) -> None:
        self._server = server
        self._timeout = timeout
        self._factory = mailbox_factory
        self._client_id = client_id
        self._mailbox: Any = None

    @property
    def connected(self) -> bool:
        return self._mailbox is not None

    def login(self, username: str, password: str) -> None:
        with _errors():
            mailbox = self._connect()
            try:
                mailbox.login(username, password, initial_folder=None)
            except MailboxLoginError:
                raise ProviderAuthError("the server rejected the login") from None
            self._mailbox = mailbox

    def login_oauth(self, username: str, access_token: str) -> None:
        with _errors():
            mailbox = self._connect()
            try:
                mailbox.xoauth2(username, access_token, initial_folder=None)
            except MailboxLoginError:
                raise ProviderAuthError("the server rejected the token") from None
            self._mailbox = mailbox

    def _connect(self) -> Any:
        mailbox = self._factory(self._server, self._timeout)
        if self._client_id is not None:
            self._send_id(mailbox, *self._client_id)
        return mailbox

    @staticmethod
    def _send_id(mailbox: Any, name: str, version: str) -> None:
        """RFC 2971 ID, where the server offers it. Some servers require it."""
        client = mailbox.client
        if "ID" not in getattr(client, "capabilities", ()):
            return
        try:
            client.xatom("ID", f'("name" "{name}" "version" "{version}")')
        except (imaplib.IMAP4.error, OSError):
            pass

    def read_capabilities(self) -> frozenset[str]:
        """Connect without logging in and return what the server announces
        after TLS or STARTTLS. Sends no credential."""
        with _errors():
            mailbox = self._factory(self._server, self._timeout)
            try:
                return frozenset(str(c).upper() for c in mailbox.client.capabilities)
            finally:
                _quietly_logout(mailbox)

    def logout(self) -> None:
        mailbox, self._mailbox = self._mailbox, None
        if mailbox is not None:
            _quietly_logout(mailbox)

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

    def folder_state(self, folder: str) -> tuple[int, int, int]:
        """UIDVALIDITY, UIDNEXT and MESSAGES of a folder, without selecting
        it. Together they change whenever a message arrives or leaves."""
        with _errors():
            status = self._require().folder.status(
                folder, ["UIDVALIDITY", "UIDNEXT", "MESSAGES"]
            )
        return (
            int(status["UIDVALIDITY"]),
            int(status.get("UIDNEXT", 0)),
            int(status.get("MESSAGES", 0)),
        )

    def fetch_message_ids(self, uids: list[int]) -> dict[int, str | None]:
        """The ``Message-ID`` header of each UID in the selected folder. Reads
        only that header and never sets ``\\Seen``."""
        if not uids:
            return {}
        with _errors():
            status, data = self._require().client.uid(
                "fetch",
                ",".join(str(u) for u in uids),
                "(UID BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])",
            )
        if status != "OK":
            raise ProviderError("the server refused to hand out message headers")
        found: dict[int, str | None] = {}
        for index, part in enumerate(data):
            if not (isinstance(part, tuple) and len(part) == 2):
                continue
            # The UID comes before the header, or after it in the next part.
            match = _UID.search(part[0])
            if match is None and index + 1 < len(data):
                following = data[index + 1]
                if isinstance(following, bytes):
                    match = _UID.search(following)
            if match is not None:
                found[int(match.group(1))] = _message_id(part[1])
        return found

    def server_capabilities(self) -> frozenset[str]:
        """What the server announces now, after the login."""
        with _errors():
            status, data = self._require().client.capability()
        if status != "OK" or not data or not isinstance(data[0], bytes):
            return frozenset()
        return frozenset(data[0].decode(errors="replace").upper().split())

    def idle(
        self,
        timeout: float,
        stopped: Callable[[], bool],
        step: float = IDLE_STEP,
        clock: Callable[[], float] = time.monotonic,
    ) -> bool:
        """IDLE in the selected folder until the server reports a change,
        ``timeout`` passes or ``stopped`` says so. Looks at ``stopped`` every
        ``step`` seconds, which costs no traffic. True on a change."""
        with _errors():
            idle = self._require().idle
            idle.start()
            try:
                deadline = clock() + timeout
                while not stopped():
                    remaining = deadline - clock()
                    if remaining <= 0:
                        return False
                    lines = idle.poll(timeout=min(step, remaining))
                    if any(_BYE.match(line) for line in lines):
                        raise ProviderUnavailableError(
                            "the mail server ended the connection"
                        )
                    if any(_CHANGE.search(line) for line in lines):
                        return True
                return False
            finally:
                if self._mailbox is not None:
                    try:
                        idle.stop()
                    except (ImapToolsError, imaplib.IMAP4.error, OSError):
                        # The connection is spoiled. Start afresh next time.
                        self.logout()

    def _require(self) -> Any:
        if self._mailbox is None:
            raise ProviderError("not connected")
        return self._mailbox


_UID = re.compile(rb"UID (\d+)")
_CHANGE = re.compile(rb"^\* \d+ (EXISTS|EXPUNGE|FETCH)\b|^\* VANISHED\b", re.I)
_BYE = re.compile(rb"^\* BYE\b", re.I)


def _message_id(header_block: bytes) -> str | None:
    value = BytesHeaderParser().parsebytes(header_block).get("Message-ID")
    if not value:
        return None
    # Folded headers keep their line breaks. The id itself has no spaces.
    return "".join(str(value).split()) or None


def _quietly_logout(mailbox: Any) -> None:
    try:
        mailbox.logout()
    except (ImapToolsError, imaplib.IMAP4.error, OSError):
        pass


@contextmanager
def _errors() -> Iterator[None]:
    try:
        yield
    except (ProviderAuthError, ProviderError):
        raise
    except TimeoutError:
        raise ProviderUnavailableError(
            "the mail server did not answer in time"
        ) from None
    except (ssl.SSLError, ssl.CertificateError) as exc:
        raise ProviderError(f"TLS with the mail server failed: {exc}") from None
    except imaplib.IMAP4.abort as exc:
        raise ProviderUnavailableError(
            f"the mail server dropped the connection: {exc}"
        ) from None
    except (ImapToolsError, imaplib.IMAP4.error) as exc:
        raise ProviderError(f"the mail server answered with an error: {exc}") from None
    except OSError as exc:
        raise ProviderUnavailableError(
            f"the mail server is not reachable: {exc}"
        ) from None
