"""One IMAP session. The only module that imports ``imapclient``.

Synchronous, like the library. The adapter runs it in a worker thread and
never calls it from two threads at once. Every library error leaves this
module as a ``MailboxApiError``. What is fetched of a message is parsed in
``parse``; this module only speaks the protocol.
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

from imapclient import IMAPClient
from imapclient.exceptions import LoginError

from ....errors import (
    NotSupportedError,
    ProviderAuthError,
    ProviderError,
    ProviderUnavailableError,
)
from .parse import FetchedMessage

ClientFactory = Callable[..., Any]

# How often a waiting IDLE looks whether it should stop. Costs no traffic.
IDLE_STEP = 5.0

_HEADER = "BODY.PEEK[HEADER]"
_WHOLE = "BODY.PEEK[]"
_MESSAGE_ID = "BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)]"
# What an untagged response during IDLE says changed.
_CHANGES = {b"EXISTS", b"EXPUNGE", b"FETCH", b"VANISHED"}


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
    subscribed: bool | None = None  # None: not asked


@dataclass(frozen=True)
class SearchCriteria:
    text: str | None = None
    unread: bool | None = None
    before_uid: int | None = None


def _default_client(server: ImapServer, timeout: float) -> Any:
    context = ssl.create_default_context()
    if server.security == "starttls":
        client = IMAPClient(server.host, server.port, ssl=False, timeout=timeout)
        client.starttls(context)
        return client
    return IMAPClient(
        server.host, server.port, ssl=True, ssl_context=context, timeout=timeout
    )


class ImapSession:
    def __init__(
        self,
        server: ImapServer,
        timeout: float = 30.0,
        client_factory: ClientFactory = _default_client,
        client_id: tuple[str, str] | None = None,
    ) -> None:
        self._server = server
        self._timeout = timeout
        self._factory = client_factory
        self._client_id = client_id
        self._client: Any = None

    @property
    def connected(self) -> bool:
        return self._client is not None

    def login(self, username: str, password: str) -> None:
        with _errors():
            client = self._connect()
            try:
                client.login(username, password)
            except LoginError:
                _quietly_logout(client)
                raise ProviderAuthError("the server rejected the login") from None
            self._client = client

    def login_oauth(self, username: str, access_token: str) -> None:
        with _errors():
            client = self._connect()
            try:
                client.oauth2_login(username, access_token)
            except LoginError:
                _quietly_logout(client)
                raise ProviderAuthError("the server rejected the token") from None
            self._client = client

    def _connect(self) -> Any:
        client = self._factory(self._server, self._timeout)
        if self._client_id is not None:
            self._send_id(client, *self._client_id)
        return client

    @staticmethod
    def _send_id(client: Any, name: str, version: str) -> None:
        """RFC 2971 ID, where the server offers it. Some servers require it."""
        if b"ID" not in client.capabilities():
            return
        try:
            client.id_({"name": name, "version": version})
        except (imaplib.IMAP4.error, OSError):
            pass

    def read_capabilities(self) -> frozenset[str]:
        """Connect without logging in and return what the server announces
        after TLS or STARTTLS. Sends no credential."""
        with _errors():
            client = self._factory(self._server, self._timeout)
            try:
                return _capabilities(client)
            finally:
                _quietly_logout(client)

    def server_capabilities(self) -> frozenset[str]:
        """What the server announces now, after the login."""
        with _errors():
            return _capabilities(self._require())

    def logout(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            _quietly_logout(client)

    def list_folders(self, subscriptions: bool = False) -> list[RawFolder]:
        """Every folder. With ``subscriptions`` also whether each one is
        subscribed, which costs one more command (LSUB)."""
        with _errors():
            client = self._require()
            subscribed = (
                {str(name) for _, _, name in client.list_sub_folders()}
                if subscriptions
                else None
            )
            return [
                RawFolder(
                    str(name),
                    _text(delimiter) if delimiter else None,
                    tuple(_text(flag) for flag in flags),
                    None if subscribed is None else str(name) in subscribed,
                )
                for flags, delimiter, name in client.list_folders()
            ]

    def select(self, folder: str) -> int:
        """Select a folder read-only, return its UIDVALIDITY."""
        with _errors():
            answer = self._require().select_folder(folder, readonly=True)
        return int(answer[b"UIDVALIDITY"])

    def select_writable(self, folder: str) -> tuple[int, frozenset[str]]:
        """Select a folder read-write. Returns its UIDVALIDITY and the flags
        the server keeps (``PERMANENTFLAGS``); ``\\*`` means any keyword."""
        with _errors():
            answer = self._require().select_folder(folder, readonly=False)
        if b"READ-ONLY" in answer:
            raise ProviderError(f"the folder {folder} is read-only on the server")
        permanent = answer.get(b"PERMANENTFLAGS", ())
        return int(answer[b"UIDVALIDITY"]), frozenset(_text(f) for f in permanent)

    def store_flags(self, uid: int, add: list[str], remove: list[str]) -> None:
        """Set and clear flags of one message in the selected folder."""
        with _errors():
            client = self._require()
            if add:
                client.add_flags([uid], add, silent=True)
            if remove:
                client.remove_flags([uid], remove, silent=True)

    def move(self, uid: int, target: str) -> int | None:
        """Move one message of the selected folder into ``target``. Returns
        its UID there where the server reports it (``COPYUID``, RFC 4315).
        Needs ``MOVE``, or ``UIDPLUS`` to copy and expunge just this one."""
        with _errors():
            client = self._require()
            announced = _capabilities(client)
            # imaplib files response codes such as [COPYUID ...] here.
            codes = client._imap.untagged_responses
            codes.pop("COPYUID", None)
            if "MOVE" in announced:
                answer = client.move([uid], target)
            elif "UIDPLUS" in announced:
                answer = client.copy([uid], target)
                client.add_flags([uid], ["\\Deleted"], silent=True)
                client.uid_expunge([uid])
            else:
                raise NotSupportedError(
                    "the mail server offers neither MOVE nor UIDPLUS: moving "
                    "would expunge other deleted messages of the folder too"
                )
            reported = codes.pop("COPYUID", None) or [answer]
        return _new_uid(reported, uid)

    def search_message_id(self, header: str) -> list[int]:
        """UIDs in the selected folder with this ``Message-ID``."""
        with _errors():
            return sorted(
                int(u) for u in self._require().search(["HEADER", "Message-ID", header])
            )

    def folder_state(self, folder: str) -> tuple[int, int, int]:
        """UIDVALIDITY, UIDNEXT and MESSAGES of a folder, without selecting
        it. Together they change whenever a message arrives or leaves."""
        with _errors():
            status = self._require().folder_status(
                folder, ["UIDVALIDITY", "UIDNEXT", "MESSAGES"]
            )
        return (
            int(status[b"UIDVALIDITY"]),
            int(status.get(b"UIDNEXT", 0)),
            int(status.get(b"MESSAGES", 0)),
        )

    def search(self, criteria: SearchCriteria) -> list[int]:
        """UIDs in the selected folder, ascending."""
        query: list[str] = []
        if criteria.text:
            query += ["TEXT", criteria.text]
        if criteria.unread is not None:
            query.append("UNSEEN" if criteria.unread else "SEEN")
        charset = "UTF-8" if criteria.text and not criteria.text.isascii() else None
        with _errors():
            uids = sorted(
                int(u) for u in self._require().search(query or "ALL", charset)
            )
        if criteria.before_uid is not None:
            uids = [u for u in uids if u < criteria.before_uid]
        return uids

    def fetch_headers(self, uids: list[int]) -> list[FetchedMessage]:
        """Flags and headers. Never sets ``\\Seen``."""
        return [
            FetchedMessage(uid, _flags(data), _part(data, b"BODY[HEADER]"))
            for uid, data in self._fetch(uids, ["FLAGS", _HEADER]).items()
        ]

    def fetch_message(self, uid: int) -> FetchedMessage | None:
        found = self._fetch([uid], ["FLAGS", _WHOLE]).get(uid)
        if found is None:
            return None
        return FetchedMessage(uid, _flags(found), _part(found, b"BODY[]"))

    def fetch_raw(self, uid: int) -> bytes | None:
        found = self._fetch([uid], [_WHOLE]).get(uid)
        return _part(found, b"BODY[]") if found is not None else None

    def fetch_message_ids(self, uids: list[int]) -> dict[int, str | None]:
        """The ``Message-ID`` header of each UID in the selected folder. Reads
        only that header and never sets ``\\Seen``."""
        return {
            uid: _message_id(_part(data, b"BODY[HEADER.FIELDS"))
            for uid, data in self._fetch(uids, [_MESSAGE_ID]).items()
        }

    def _fetch(self, uids: list[int], items: list[str]) -> dict[int, dict[bytes, Any]]:
        if not uids:
            return {}
        with _errors():
            found = self._require().fetch(uids, items)
        return {int(uid): data for uid, data in found.items()}

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
            client = self._require()
            client.idle()
            try:
                deadline = clock() + timeout
                while not stopped():
                    remaining = deadline - clock()
                    if remaining <= 0:
                        return False
                    responses = client.idle_check(timeout=min(step, remaining))
                    if any(r and r[0] == b"BYE" for r in responses):
                        raise ProviderUnavailableError(
                            "the mail server ended the connection"
                        )
                    if any(_CHANGES.intersection(r[:2]) for r in responses):
                        return True
                return False
            finally:
                if self._client is not None:
                    try:
                        client.idle_done()
                    except (imaplib.IMAP4.error, OSError):
                        # The connection is spoiled. Start afresh next time.
                        self.logout()

    def _require(self) -> Any:
        if self._client is None:
            raise ProviderError("not connected")
        return self._client


def _text(value: bytes | str) -> str:
    return value.decode(errors="replace") if isinstance(value, bytes) else value


def _capabilities(client: Any) -> frozenset[str]:
    return frozenset(_text(c).upper() for c in client.capabilities())


def _flags(data: dict[bytes, Any]) -> tuple[str, ...]:
    return tuple(_text(flag) for flag in data.get(b"FLAGS", ()))


def _part(data: dict[bytes, Any], key: bytes) -> bytes:
    """A fetched body section. Servers may spell the key a little
    differently, so the start is enough."""
    for name, value in data.items():
        if isinstance(name, bytes) and name.startswith(key):
            return bytes(value or b"")
    return b""


def _new_uid(reported: list[Any], uid: int) -> int | None:
    """The UID ``uid`` got, from ``COPYUID <validity> <old set> <new set>``."""
    for item in reported:
        text = _text(item) if isinstance(item, bytes | str) else ""
        match = re.search(r"(?:COPYUID )?\d+ ([\d:,]+) ([\d:,]+)", text)
        if match is None:
            continue
        old, new = _uid_set(match.group(1)), _uid_set(match.group(2))
        if uid in old and len(old) == len(new):
            return new[old.index(uid)]
    return None


def _uid_set(text: str) -> list[int]:
    """``3:5,9`` to ``[3, 4, 5, 9]``, in the order given."""
    uids: list[int] = []
    for part in text.split(","):
        first, _, last = part.partition(":")
        start, end = int(first), int(last or first)
        step = 1 if end >= start else -1
        uids += range(start, end + step, step)
    return uids


def _message_id(header_block: bytes) -> str | None:
    value = BytesHeaderParser().parsebytes(header_block).get("Message-ID")
    if not value:
        return None
    # Folded headers keep their line breaks. The id itself has no spaces.
    return "".join(str(value).split()) or None


def _quietly_logout(client: Any) -> None:
    try:
        client.logout()
    except (imaplib.IMAP4.error, OSError):
        pass


@contextmanager
def _errors() -> Iterator[None]:
    try:
        yield
    except (ProviderAuthError, ProviderError, NotSupportedError):
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
    except imaplib.IMAP4.error as exc:
        raise ProviderError(f"the mail server answered with an error: {exc}") from None
    except OSError as exc:
        raise ProviderUnavailableError(
            f"the mail server is not reachable: {exc}"
        ) from None
