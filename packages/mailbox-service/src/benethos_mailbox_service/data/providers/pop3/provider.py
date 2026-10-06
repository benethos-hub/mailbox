"""The POP3 adapter: one account, one mailbox, no folders, no flags.

POP3 knows one mailbox, read and deleted by message number, with a unique
id per message (UIDL). It has no folders, no flags, no search and no push
(CONCEPT 5.2). The adapter offers the inbox as the one folder, lists and
reads its messages, and deletes them for good. Sending goes over SMTP
when the settings name a server.

A POP3 session sees the mailbox as it was at its login, and the server
locks the mailbox while it lasts. So every step logs in, does its work and
ends the session, under the account's lock, in a worker thread. The
credential is decrypted right before the login and not kept. ``Guard``
paces the steps as for IMAP (CONCEPT 5.9).
"""

from __future__ import annotations

import hashlib
import itertools
import threading
import time
from collections.abc import Callable
from functools import partial
from typing import TypeVar

import anyio

from ....common.chunks import batched
from ....common.ratelimit import Clock, Sleep
from ....errors import (
    BadRequestError,
    ConflictError,
    MailboxServiceError,
    NotSupportedError,
    missing_message,
)
from ...mail import convert, parse
from ...models import (
    AttachmentContent,
    CredentialKind,
    Folder,
    MailServer,
    Message,
    MessageFilter,
    MessageSummary,
    MessageUpdate,
    Page,
    SentMessage,
    ServerProtocol,
)
from ...protocols import POP3_PORTS, Pick, Pop3Session, Server, SmtpSession
from .. import rules
from ..base import Capability, CredentialReader, FolderChanges, ProviderSettings
from ..guard import Guard, Pace
from ..sender import SmtpFactory, SmtpSender
from . import mappers

T = TypeVar("T")

SessionFactory = Callable[[Server], Pop3Session]

PROBE_TIMEOUT = 10.0

# Message-ID headers read per session during a sync.
HEADER_BATCH = 200


def settings_from(
    servers: list[MailServer], credential: CredentialKind, email: str
) -> dict[str, str | int | bool]:
    """The settings of a POP3 account from discovered servers, as
    ``Pop3Provider`` reads them. Empty without a POP3 server."""
    pop3 = next((s for s in servers if s.protocol is ServerProtocol.POP3), None)
    if pop3 is None or credential is CredentialKind.OAUTH:
        return {}
    settings: dict[str, str | int | bool] = {
        "host": pop3.host,
        "port": pop3.port,
        "security": str(pop3.security),
        "username": pop3.username or email,
    }
    smtp = next((s for s in servers if s.protocol is ServerProtocol.SMTP), None)
    if smtp is not None:
        settings["smtp_host"] = smtp.host
        settings["smtp_port"] = smtp.port
        settings["smtp_security"] = str(smtp.security)
        if smtp.username and smtp.username != settings["username"]:
            settings["smtp_username"] = smtp.username
    return settings


def probe_session(server: Server) -> Pop3Session:
    return Pop3Session(server, timeout=PROBE_TIMEOUT)


async def probe(
    host: str,
    port: int,
    security: str,
    address: str | None = None,
    session_factory: SessionFactory = probe_session,
) -> frozenset[str]:
    """The capabilities of a POP3 server, read without logging in. With
    ``address``, the connection goes there, the address just checked."""
    if security not in POP3_PORTS:
        raise BadRequestError("POP3 without encryption is not supported")
    pick = (lambda _host, _port: address) if address is not None else None
    session = session_factory(
        Server(host=host, port=port, security=security, pick=pick)
    )
    return await anyio.to_thread.run_sync(session.read_capabilities)


class Pop3Provider:
    # No flags, folders or search. Without STABLE_IDS the sync polls the
    # mailbox and compares its unique ids, as for IMAP without IDLE. The ids
    # never move, so the mapping the domain keeps stays as it was.
    capabilities: frozenset[Capability] = frozenset()

    def __init__(
        self,
        settings: ProviderSettings,
        credentials: CredentialReader,
        session_factory: SessionFactory = Pop3Session,
        clock: Clock = time.monotonic,
        sleep: Sleep = time.sleep,
        jitter: Callable[[float, float], float] | None = None,
        smtp_factory: SmtpFactory = SmtpSession,
        pick: Pick | None = None,
        pace: Pace | None = None,
    ) -> None:
        """``pick`` checks the host of each connection, POP3 and SMTP.
        ``pace`` is how fast steps go, unless the settings name a rate."""
        host = settings.get("host")
        if not host:
            raise BadRequestError("a POP3 account needs settings.host")
        security = rules.encrypted(settings, "security", "POP3")
        username = settings.get("username")
        if not username:
            raise BadRequestError("a POP3 account needs settings.username")
        if settings.get("auth", "password") != "password":
            raise BadRequestError("settings.auth must be 'password'")
        self._server = Server(
            host=str(host),
            port=rules.port_of(settings, "port", POP3_PORTS[security]),
            security=security,
            pick=pick,
        )
        self._username = str(username)
        self._credentials = credentials
        pace = pace or Pace()
        per_minute = rules.rate_of(settings, "max_requests_per_minute", pace.per_minute)
        self._guard = Guard(
            per_minute,
            pace.burst,
            clock=clock,
            sleep=sleep,
            jitter=jitter,
            attempts=pace.attempts,
            first_pause=pace.first_pause,
            longest_pause=pace.longest_pause,
            name=f"requests to {host}",
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
        self._session = session_factory(self._server)
        self._lock = threading.Lock()

    # --- MailProvider ---------------------------------------------------------

    async def list_folders(self) -> list[Folder]:
        return [mappers.inbox()]

    async def create_folder(self, name: str, parent_id: str | None) -> Folder:
        raise _no_folders()

    async def update_folder(
        self, folder_id: str, name: str, parent_id: str | None
    ) -> Folder:
        raise _no_folders()

    async def delete_folder(self, folder_id: str) -> None:
        raise _no_folders()

    async def list_messages(
        self,
        folder_id: str | None,
        *,
        limit: int,
        cursor: str | None,
        search: MessageFilter | None = None,
    ) -> Page[MessageSummary]:
        mappers.check_folder(folder_id)
        if search is not None and search.model_dump(exclude_defaults=True):
            raise NotSupportedError("a POP3 mailbox cannot be searched")
        start = mappers.parse_cursor(cursor) if cursor else None
        return await self._run(lambda session: _list(session, limit, start))

    async def get_message(self, message_id: str) -> Message:
        raw = await self.get_raw(message_id)
        return mappers.to_message(
            parse.ParsedMessage(raw), mappers.unique_id(message_id)
        )

    async def get_attachment(
        self, message_id: str, attachment_id: str
    ) -> AttachmentContent:
        raw = await self.get_raw(message_id)
        return convert.attachment(parse.ParsedMessage(raw), attachment_id)

    async def get_raw(self, message_id: str) -> bytes:
        uid = mappers.unique_id(message_id)
        return await self._run(lambda session: _message(session, uid, message_id))

    async def send(self, raw: bytes, sender: str, recipients: list[str]) -> SentMessage:
        if self._smtp is None:
            raise ConflictError(
                "the account has no SMTP server: its settings name no smtp_host"
            )
        refused = await anyio.to_thread.run_sync(
            self._smtp.send, raw, sender, recipients
        )
        # POP3 has no folder to keep a copy in.
        return SentMessage(refused=refused)

    async def list_drafts(
        self, *, limit: int, cursor: str | None
    ) -> Page[MessageSummary]:
        raise _no_drafts()

    async def save_draft(self, raw: bytes, replaces: str | None) -> MessageSummary:
        raise _no_drafts()

    async def get_draft(self, draft_id: str) -> bytes:
        raise _no_drafts()

    async def delete_draft(self, draft_id: str) -> None:
        raise _no_drafts()

    async def update_messages(
        self, message_ids: list[str], changes: MessageUpdate
    ) -> dict[str, MessageSummary | MailboxServiceError]:
        if (
            changes.unread is not None
            or changes.starred is not None
            or changes.keywords is not None
        ):
            raise NotSupportedError(
                "a POP3 mailbox keeps no read state, stars or keywords"
            )
        target = rules.move_target(changes, self.capabilities)
        if target is not None and target != mappers.folder_id():
            raise _no_folders()
        # Nothing changes: each message as it is, or why not.
        return await rules.per_id(message_ids, self._summary)

    async def delete_messages(
        self, message_ids: list[str], permanent: bool
    ) -> dict[str, MessageSummary | None | MailboxServiceError]:
        if not permanent:
            raise NotSupportedError(
                "a POP3 mailbox has no trash: a message can only be deleted for good"
            )
        wanted: dict[str, str] = {}
        results: dict[str, MessageSummary | None | MailboxServiceError] = {}
        for message_id in message_ids:
            try:
                wanted[message_id] = mappers.unique_id(message_id)
            except MailboxServiceError as exc:
                results[message_id] = exc
        if wanted:
            results.update(
                await self._retrying(
                    lambda session, retried: _delete(session, wanted, retried),
                    commit=True,
                )
            )
        return results

    # --- for the sync worker ---------------------------------------------------

    async def folder_states(self) -> dict[str, str]:
        uids = await self._run(_unique_ids)
        digest = hashlib.sha256("\n".join(uids).encode()).hexdigest()[:32]
        return {mappers.folder_id(): f"{len(uids)}.{digest}"}

    async def folder_contents(self, folder_id: str) -> list[str]:
        mappers.check_folder(folder_id)
        return [mappers.message_id(uid) for uid in await self._run(_unique_ids)]

    async def message_headers(self, message_ids: list[str]) -> dict[str, str | None]:
        wanted = {}
        for message_id in message_ids:
            try:
                wanted[mappers.unique_id(message_id)] = message_id
            except MailboxServiceError:
                continue  # no id of this adapter: left out, as one that is gone
        found: dict[str, str | None] = {}
        # One session per batch, so a long first sync never holds the
        # mailbox for long.
        for uids in batched(list(wanted), HEADER_BATCH):
            batch = {uid: wanted[uid] for uid in uids}
            found.update(await self._run(partial(_message_ids, wanted=batch)))
        return found

    async def flag_changes(
        self, folder_id: str, since: str, message_ids: list[str]
    ) -> list[str]:
        return []  # POP3 has no flags

    async def folder_changes(self, folder_id: str, token: str | None) -> FolderChanges:
        raise NotSupportedError("POP3 mailboxes are compared by their state")

    async def wait_for_change(self, timeout: float) -> bool:
        raise NotSupportedError("POP3 has no push: the mailbox is polled")

    async def verify(self) -> None:
        await anyio.to_thread.run_sync(self._verify)

    async def close(self) -> None:
        await anyio.to_thread.run_sync(self._close)

    # --- plumbing ---------------------------------------------------------------

    async def _summary(self, message_id: str) -> MessageSummary:
        uid = mappers.unique_id(message_id)
        return await self._run(lambda session: _summary(session, uid, message_id))

    async def _run(self, operation: Callable[[Pop3Session], T]) -> T:
        return await self._retrying(lambda session, _retried: operation(session))

    async def _retrying(
        self, operation: Callable[[Pop3Session, bool], T], commit: bool = False
    ) -> T:
        """One step in a session of its own, retried by the guard while the
        server is unreachable. ``operation`` learns whether this is a retry,
        so that finding its work done counts as done. With ``commit`` the
        session ends with QUIT, which makes deletions take effect."""
        attempts = itertools.count()
        return await anyio.to_thread.run_sync(
            self._locked, lambda session: operation(session, next(attempts) > 0), commit
        )

    def _locked(self, operation: Callable[[Pop3Session], T], commit: bool) -> T:
        session = self._session

        def step() -> T:
            # A session sees the mailbox as at its login: never an old one.
            session.logout()
            self._login(session)
            try:
                result = operation(session)
                if commit:
                    session.commit()
            finally:
                session.logout()
            return result

        with self._lock:
            return self._guard.attempts(step, drop=session.logout)

    def _verify(self) -> None:
        with self._lock:
            self._guard.reset()
            self._session.logout()
            with self._guard.refused_logins():
                self._login(self._session)
                try:
                    # A server without UIDL is refused here, at the start.
                    _unique_ids(self._session)
                finally:
                    self._session.logout()
                if self._smtp is not None:
                    self._smtp.verify()

    def _close(self) -> None:
        with self._lock:
            self._session.logout()

    def _secret(self) -> str:
        """The credential for the login, decrypted for this one use."""
        return self._credentials("password").get_secret_value()

    def _login(self, session: Pop3Session) -> None:
        session.login(self._username, self._secret())


# --- the steps, each in one session ------------------------------------------


def _unique_ids(session: Pop3Session) -> list[str]:
    return [uid for _, uid in session.unique_ids()]


def _numbers(session: Pop3Session) -> dict[str, int]:
    """The message number of each unique id in this session."""
    return {uid: number for number, uid in session.unique_ids()}


def _list(
    session: Pop3Session, limit: int, start: tuple[str, int] | None
) -> Page[MessageSummary]:
    """Newest first: the highest message numbers are the latest to arrive."""
    newest = list(reversed(session.unique_ids()))
    position = 0
    if start is not None:
        uid, at = start
        positions = {u: i for i, (_, u) in enumerate(newest)}
        # After the cursor's message. If it is gone since, the next one has
        # moved up to its place.
        position = positions[uid] + 1 if uid in positions else at
    page = newest[position : position + limit]
    items = [
        mappers.to_summary(parse.ParsedMessage(session.headers(number)), uid)
        for number, uid in page
    ]
    more = position + limit < len(newest)
    return Page[MessageSummary](
        items=items,
        next_cursor=mappers.cursor(page[-1][1], position + len(page) - 1)
        if more and page
        else None,
    )


def _summary(session: Pop3Session, uid: str, message_id: str) -> MessageSummary:
    number = _numbers(session).get(uid)
    if number is None:
        raise missing_message(message_id)
    return mappers.to_summary(parse.ParsedMessage(session.headers(number)), uid)


def _message(session: Pop3Session, uid: str, message_id: str) -> bytes:
    number = _numbers(session).get(uid)
    if number is None:
        raise missing_message(message_id)
    return session.message(number)


def _message_ids(session: Pop3Session, wanted: dict[str, str]) -> dict[str, str | None]:
    """The Message-ID header of each wanted message that is there."""
    found: dict[str, str | None] = {}
    for uid, number in _numbers(session).items():
        if uid in wanted:
            found[wanted[uid]] = parse.ParsedMessage(session.headers(number)).message_id
    return found


def _delete(
    session: Pop3Session, wanted: dict[str, str], retried: bool
) -> dict[str, MessageSummary | None | MailboxServiceError]:
    """Mark each wanted message deleted. They go when the session ends with
    QUIT. On a retry a message that is gone counts as deleted: the first
    try may have ended its session before the connection dropped."""
    numbers = _numbers(session)
    results: dict[str, MessageSummary | None | MailboxServiceError] = {}
    for message_id, uid in wanted.items():
        number = numbers.get(uid)
        if number is None:
            results[message_id] = None if retried else missing_message(message_id)
            continue
        session.delete(number)
        results[message_id] = None
    return results


def _no_folders() -> NotSupportedError:
    return NotSupportedError("a POP3 mailbox has one folder, the inbox")


def _no_drafts() -> NotSupportedError:
    return NotSupportedError("a POP3 mailbox keeps no drafts")
