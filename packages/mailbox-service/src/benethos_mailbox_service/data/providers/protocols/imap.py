"""One IMAP session. The only module that imports ``imapclient``.

Synchronous, like the library. The adapter runs it in a worker thread and
never calls it from two threads at once. Every library error leaves this
module as a ``MailboxServiceError``. What is fetched of a message is parsed in
``data.mail.parse``. This module only speaks the protocol.
"""

from __future__ import annotations

import imaplib
import re
import ssl
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from email.parser import BytesHeaderParser
from typing import Any

from imapclient import IMAPClient
from imapclient.exceptions import LoginError

from ....errors import (
    BadRequestError,
    NotFoundError,
    NotSupportedError,
    ProviderAuthError,
    ProviderError,
    ProviderUnavailableError,
)
from ...mail import fields
from ...mail.parse import ParsedMessage

ClientFactory = Callable[..., Any]

# How often a waiting IDLE looks whether it should stop. Costs no traffic.
IDLE_STEP = 5.0

_HEADER = "BODY.PEEK[HEADER]"
_WHOLE = "BODY.PEEK[]"
_MESSAGE_ID = "BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)]"
# What an untagged response during IDLE says changed.
_CHANGES = {b"EXISTS", b"EXPUNGE", b"FETCH", b"VANISHED"}
# Control characters, not allowed in a search text.
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


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


class FetchedMessage(ParsedMessage):
    """A fetched message: UID and flags as the server reported them, the
    rest parsed from the fetched bytes."""

    def __init__(self, uid: int, flags: tuple[str, ...], raw: bytes) -> None:
        super().__init__(raw)
        self.uid = str(uid)
        self.flags = flags


@dataclass(frozen=True)
class SearchCriteria:
    """IMAP SEARCH keys (RFC 3501 6.4.4). Fields left out do not narrow."""

    text: str | None = None  # TEXT: headers and body
    sender: str | None = None  # FROM
    to: str | None = None  # TO
    subject: str | None = None  # SUBJECT
    since: date | None = None  # SINCE: on or after this day
    before: date | None = None  # BEFORE: before this day
    unread: bool | None = None  # UNSEEN or SEEN
    flagged: bool | None = None  # FLAGGED or UNFLAGGED
    # Content-Type multipart/mixed, as has_attachments reads it in a summary.
    mixed: bool | None = None
    before_uid: int | None = None


DEFAULT_PORTS = {"tls": 993, "starttls": 143}


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
        self._log_in(lambda c: c.login(username, password), "login")

    def login_oauth(self, username: str, access_token: str) -> None:
        self._log_in(lambda c: c.oauth2_login(username, access_token), "token")

    def _log_in(self, authenticate: Callable[[Any], Any], what: str) -> None:
        with _errors():
            client = self._connect()
            try:
                authenticate(client)
            except LoginError:
                _quietly_logout(client)
                raise ProviderAuthError(f"the server rejected the {what}") from None
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
            answer = self._select_folder(folder, readonly=True)
        return int(answer[b"UIDVALIDITY"])

    def select_writable(self, folder: str) -> tuple[int, frozenset[str]]:
        """Select a folder read-write. Returns its UIDVALIDITY and the flags
        the server keeps (``PERMANENTFLAGS``). ``\\*`` means any keyword."""
        with _errors():
            answer = self._select_folder(folder, readonly=False)
        if b"READ-ONLY" in answer:
            raise ProviderError(f"the folder {folder} is read-only on the server")
        permanent = answer.get(b"PERMANENTFLAGS", ())
        return int(answer[b"UIDVALIDITY"]), frozenset(_text(f) for f in permanent)

    def store_flags(self, uids: list[int], add: list[str], remove: list[str]) -> None:
        """Set and clear the same flags on messages of the selected folder."""
        with _errors():
            client = self._require()
            if add:
                client.add_flags(uids, add, silent=True)
            if remove:
                client.remove_flags(uids, remove, silent=True)

    def move(self, uids: list[int], target: str) -> dict[int, int]:
        """Move messages of the selected folder into ``target`` with one
        command. Returns their UIDs there, as far as the server reports them
        (``COPYUID``, RFC 4315). Needs ``MOVE``, or ``UIDPLUS`` to copy and
        expunge just these."""
        with _errors():
            client = self._require()
            announced = _capabilities(client)
            if "MOVE" in announced:
                reported = _with_code(
                    client, "COPYUID", lambda: client.move(uids, target)
                )
            elif "UIDPLUS" in announced:

                def copy_and_expunge() -> Any:
                    answer = client.copy(uids, target)
                    client.add_flags(uids, ["\\Deleted"], silent=True)
                    client.uid_expunge(uids)
                    return answer

                reported = _with_code(client, "COPYUID", copy_and_expunge)
            else:
                raise NotSupportedError(
                    "the mail server offers neither MOVE nor UIDPLUS: moving "
                    "would expunge other deleted messages of the folder too"
                )
        return _new_uids(reported)

    def expunge(self, uids: list[int]) -> None:
        """Delete messages of the selected folder for good. Needs
        ``UIDPLUS``: a plain EXPUNGE would take every message marked
        deleted with it, other clients' too."""
        with _errors():
            client = self._require()
            if "UIDPLUS" not in _capabilities(client):
                raise NotSupportedError(
                    "the mail server offers no UIDPLUS: deleting one message "
                    "for good would expunge other deleted messages too"
                )
            client.add_flags(uids, ["\\Deleted"], silent=True)
            client.uid_expunge(uids)

    def append(self, folder: str, raw: bytes, flags: list[str]) -> int | None:
        """Store a message in ``folder``. Returns its UID where the server
        reports it (``APPENDUID``, RFC 4315)."""
        with _errors():
            client = self._require()
            reported = _with_code(
                client,
                "APPENDUID",
                lambda: client.append(
                    folder, raw, flags=flags, msg_time=datetime.now(UTC)
                ),
            )
        for item in reported:
            match = re.search(r"(?:APPENDUID )?\d+ (\d+)", _text(item) if item else "")
            if match:
                return int(match.group(1))
        return None

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
        query: list[Any] = []
        texts = {
            "TEXT": criteria.text,
            "FROM": criteria.sender,
            "TO": criteria.to,
            "SUBJECT": criteria.subject,
        }
        for key, value in texts.items():
            if value:
                if _CONTROL.search(value):
                    # The library quotes but keeps line breaks: they would end
                    # the command and start one of the caller's choosing.
                    raise BadRequestError(
                        "search text must not hold control characters"
                    )
                query += [key, value]
        if criteria.since is not None:
            query += ["SINCE", criteria.since]
        if criteria.before is not None:
            query += ["BEFORE", criteria.before]
        if criteria.unread is not None:
            query.append("UNSEEN" if criteria.unread else "SEEN")
        if criteria.flagged is not None:
            query.append("FLAGGED" if criteria.flagged else "UNFLAGGED")
        if criteria.mixed is not None:
            mixed = ["HEADER", "Content-Type", "multipart/mixed"]
            query += mixed if criteria.mixed else ["NOT", *mixed]
        wide = any(v and not v.isascii() for v in texts.values())
        with _errors():
            uids = sorted(
                int(u)
                for u in self._require().search(
                    query or "ALL", "UTF-8" if wide else None
                )
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

    def _select_folder(self, folder: str, readonly: bool) -> dict[bytes, Any]:
        """SELECT or EXAMINE. A folder that is gone, e.g. renamed by another
        client, is ``NotFoundError`` rather than a server error."""
        client = self._require()
        try:
            answer: dict[bytes, Any] = client.select_folder(folder, readonly=readonly)
        except imaplib.IMAP4.error:
            if not client.folder_exists(folder):
                raise NotFoundError(f"folder {folder} not found") from None
            raise
        return answer

    # --- folders ---------------------------------------------------------------------

    def personal_namespace(self) -> tuple[str, str | None]:
        """Where top-level folders of the user go (RFC 2342), e.g.
        ``("INBOX.", ".")`` on servers that keep all folders below the inbox,
        and its delimiter."""
        with _errors():
            client = self._require()
            if "NAMESPACE" not in _capabilities(client):
                return "", None
            personal = client.namespace().personal
        if not personal:
            return "", None
        prefix, delimiter = personal[0]
        return _text(prefix), _text(delimiter) if delimiter else None

    def create_folder(self, name: str) -> None:
        """Create and subscribe: mail clients such as Outlook list only
        subscribed folders."""
        with _errors():
            client = self._require()
            client.create_folder(name)
            client.subscribe_folder(name)

    def rename_folder(self, old: str, new: str) -> None:
        """Rename, and move the subscription along."""
        with _errors():
            client = self._require()
            client.rename_folder(old, new)
            client.subscribe_folder(new)
            _quietly(lambda: client.unsubscribe_folder(old))

    def delete_folder(self, name: str) -> None:
        """Delete, and drop the subscription, which would otherwise stay."""
        with _errors():
            client = self._require()
            _quietly(lambda: client.unsubscribe_folder(name))
            client.delete_folder(name)

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


def _new_uids(reported: list[Any]) -> dict[int, int]:
    """Old UID to new, from ``COPYUID <validity> <old set> <new set>``."""
    found: dict[int, int] = {}
    for item in reported:
        text = _text(item) if isinstance(item, bytes | str) else ""
        match = re.search(r"(?:COPYUID )?\d+ ([\d:,]+) ([\d:,]+)", text)
        if match is None:
            continue
        old, new = _uid_set(match.group(1)), _uid_set(match.group(2))
        if len(old) == len(new):
            found.update(zip(old, new, strict=True))
    return found


def _uid_set(text: str) -> list[int]:
    """``3:5,9`` to ``[3, 4, 5, 9]``, in the order given."""
    uids: list[int] = []
    for part in text.split(","):
        first, _, last = part.partition(":")
        start, end = int(first), int(last or first)
        step = 1 if end >= start else -1
        uids += range(start, end + step, step)
    return uids


def _with_code(client: Any, code: str, command: Callable[[], Any]) -> list[Any]:
    """Run a command and return the response code it produced, e.g. the
    ``[COPYUID ...]`` of a move, or else the command's own answer. imaplib
    files such codes in the client's untagged responses. This is the one
    place that reaches into it."""
    codes = client._imap.untagged_responses
    codes.pop(code, None)
    answer = command()
    found: list[Any] = codes.pop(code, None) or [answer]
    return found


def _message_id(header_block: bytes) -> str | None:
    return fields.message_id(
        BytesHeaderParser().parsebytes(header_block).get("Message-ID")
    )


def _quietly(command: Callable[[], Any]) -> None:
    """A command whose failure changes nothing, e.g. dropping a subscription
    that does not exist."""
    try:
        command()
    except imaplib.IMAP4.error:
        pass


def _quietly_logout(client: Any) -> None:
    try:
        client.logout()
    except (imaplib.IMAP4.error, OSError):
        pass


@contextmanager
def _errors() -> Iterator[None]:
    try:
        yield
    except (ProviderAuthError, ProviderError, NotSupportedError, NotFoundError):
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
