"""The IMAP adapter: one account, one connection, one lock.

IMAP connections are stateful (the selected folder), so every operation runs
as one uninterrupted sequence under the account's lock, in a worker thread.
The credential is decrypted right before a login and not kept.

Towards the server the adapter is careful (CONCEPT 5.9): every request passes
the account's rate limiter, a rejected login is not tried again until the
credential changes, and an unreachable server is retried with backoff and
then left alone for a growing pause.
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable
from functools import partial
from typing import Any, TypeVar

import anyio

from .... import __version__
from ....errors import (
    BadRequestError,
    NotFoundError,
    ProviderAuthError,
    ProviderError,
    ProviderUnavailableError,
)
from ...models import AttachmentContent, Folder, Message, MessageSummary, Page
from ..base import Capability, CredentialReader
from ..ratelimit import Clock, Sleep, TokenBucket, backoff
from . import mappers
from .client import ImapServer, ImapSession, SearchCriteria

T = TypeVar("T")

SessionFactory = Callable[[ImapServer], ImapSession]

DEFAULT_PORTS = {"tls": 993, "starttls": 143}

CLIENT_ID = ("benethos-mailbox-api", __version__)

# A cautious default for servers nobody has told us about.
DEFAULT_REQUESTS_PER_MINUTE = 60
ATTEMPTS = 3
FIRST_PAUSE = 30.0
LONGEST_PAUSE = 900.0


PROBE_TIMEOUT = 10.0


def default_session(server: ImapServer) -> ImapSession:
    return ImapSession(server, client_id=CLIENT_ID)


def probe_session(server: ImapServer) -> ImapSession:
    return ImapSession(server, timeout=PROBE_TIMEOUT)


async def probe(
    host: str,
    port: int,
    security: str,
    session_factory: SessionFactory = probe_session,
) -> frozenset[str]:
    """The capabilities of an IMAP server, read without logging in."""
    if security not in DEFAULT_PORTS:
        raise BadRequestError("IMAP without encryption is not supported")
    session = session_factory(ImapServer(host=host, port=port, security=security))
    return await anyio.to_thread.run_sync(session.read_capabilities)


class ImapProvider:
    capabilities = frozenset({Capability.SERVER_SEARCH})

    def __init__(
        self,
        settings: Any,
        credentials: CredentialReader,
        session_factory: SessionFactory = default_session,
        clock: Clock = time.monotonic,
        sleep: Sleep = time.sleep,
        jitter: Callable[[float, float], float] | None = None,
    ) -> None:
        host = settings.get("host")
        if not host:
            raise BadRequestError("an IMAP account needs settings.host")
        security = settings.get("security", "tls")
        if security not in DEFAULT_PORTS:
            raise BadRequestError(
                "settings.security must be 'tls' or 'starttls': "
                "IMAP without encryption is not supported"
            )
        username = settings.get("username")
        if not username:
            raise BadRequestError("an IMAP account needs settings.username")
        auth = settings.get("auth", "password")
        if auth not in ("password", "xoauth2"):
            raise BadRequestError("settings.auth must be 'password' or 'xoauth2'")
        self._server = ImapServer(
            host=str(host),
            port=int(settings.get("port") or DEFAULT_PORTS[security]),
            security=str(security),
        )
        self._username = str(username)
        self._auth = str(auth)
        self._credentials = credentials
        self._session = session_factory(self._server)
        self._lock = threading.Lock()
        per_minute = float(
            settings.get("max_requests_per_minute") or DEFAULT_REQUESTS_PER_MINUTE
        )
        self._bucket = TokenBucket(per_minute, burst=10, clock=clock, sleep=sleep)
        self._clock = clock
        self._sleep = sleep
        self._backoff = partial(backoff, jitter=jitter) if jitter else backoff
        self._login_rejected = False
        self._failures = 0
        self._paused_until = 0.0

    # --- MailProvider ---------------------------------------------------------

    async def list_folders(self) -> list[Folder]:
        return await self._run(self._list_folders)

    async def list_messages(
        self,
        folder_id: str | None,
        *,
        limit: int,
        cursor: str | None,
        query: str | None,
        unread: bool | None,
    ) -> Page[MessageSummary]:
        return await self._run(
            lambda: self._list_messages(folder_id, limit, cursor, query, unread)
        )

    async def get_message(self, message_id: str) -> Message:
        return await self._run(lambda: self._get_message(message_id))

    async def get_attachment(
        self, message_id: str, attachment_id: str
    ) -> AttachmentContent:
        return await self._run(lambda: self._get_attachment(message_id, attachment_id))

    async def get_raw(self, message_id: str) -> bytes:
        return await self._run(lambda: self._get_raw(message_id))

    async def verify(self) -> None:
        await anyio.to_thread.run_sync(self._verify)

    async def close(self) -> None:
        await anyio.to_thread.run_sync(self._close)

    # --- the sequences, each under the lock -------------------------------------

    def _list_folders(self) -> list[Folder]:
        return mappers.to_folders(self._session.list_folders())

    def _list_messages(
        self,
        folder_id: str | None,
        limit: int,
        cursor: str | None,
        query: str | None,
        unread: bool | None,
    ) -> Page[MessageSummary]:
        folder = mappers.folder_name(folder_id) if folder_id else mappers.INBOX
        before: int | None = None
        expected_validity: int | None = None
        if cursor:
            cursor_folder, expected_validity, before = mappers.parse_cursor(cursor)
            if cursor_folder != folder:
                raise BadRequestError("the cursor belongs to another folder")
        validity = self._session.select(folder)
        if expected_validity is not None and expected_validity != validity:
            raise BadRequestError("the folder changed on the server: start again")
        uids = self._session.search(
            SearchCriteria(text=query, unread=unread, before_uid=before)
        )
        page = list(reversed(uids[-limit:]))
        messages = {int(m.uid): m for m in self._session.fetch_headers(page) if m.uid}
        items = [
            mappers.to_summary(messages[uid], folder, validity)
            for uid in page
            if uid in messages
        ]
        more = len(uids) > limit
        return Page[MessageSummary](
            items=items,
            next_cursor=mappers.cursor(folder, validity, page[-1]) if more else None,
        )

    def _fetch(self, message_id: str) -> tuple[Any, str, int]:
        folder, validity, uid = mappers.parse_message_id(message_id)
        if self._session.select(folder) != validity:
            raise NotFoundError(f"message {message_id} not found")
        message = self._session.fetch_message(uid)
        if message is None:
            raise NotFoundError(f"message {message_id} not found")
        return message, folder, validity

    def _get_message(self, message_id: str) -> Message:
        message, folder, validity = self._fetch(message_id)
        return mappers.to_message(message, folder, validity)

    def _get_attachment(self, message_id: str, attachment_id: str) -> AttachmentContent:
        index = mappers.attachment_index(attachment_id)
        message, _, _ = self._fetch(message_id)
        if index >= len(message.attachments):
            raise NotFoundError(f"attachment {attachment_id} not found")
        part = message.attachments[index]
        return AttachmentContent(
            filename=part.filename or None,
            content_type=part.content_type or "application/octet-stream",
            data=part.payload,
        )

    def _get_raw(self, message_id: str) -> bytes:
        folder, validity, uid = mappers.parse_message_id(message_id)
        if self._session.select(folder) != validity:
            raise NotFoundError(f"message {message_id} not found")
        raw = self._session.fetch_raw(uid)
        if raw is None:
            raise NotFoundError(f"message {message_id} not found")
        return raw

    def _verify(self) -> None:
        with self._lock:
            self._login_rejected = False
            self._failures = 0
            self._paused_until = 0.0
            self._session.logout()
            try:
                self._login()
            except ProviderAuthError:
                self._login_rejected = True
                raise

    def _close(self) -> None:
        with self._lock:
            self._session.logout()

    # --- plumbing ---------------------------------------------------------------

    async def _run(self, operation: Callable[[], T]) -> T:
        return await anyio.to_thread.run_sync(self._locked, operation)

    def _locked(self, operation: Callable[[], T]) -> T:
        with self._lock:
            self._check_allowed()
            last: ProviderUnavailableError | None = None
            for attempt in range(ATTEMPTS):
                if attempt:
                    self._sleep(self._backoff(attempt - 1))
                try:
                    self._bucket.acquire()
                    if not self._session.connected:
                        self._login()
                    result = operation()
                except ProviderAuthError:
                    self._session.logout()
                    self._login_rejected = True
                    raise
                except ProviderUnavailableError as exc:
                    self._session.logout()
                    last = exc
                    continue
                except ProviderError:
                    # Not a connection problem, so retrying will not help. The
                    # connection may still be in a bad state: start afresh.
                    self._session.logout()
                    raise
                self._failures = 0
                return result
            self._pause()
            assert last is not None
            raise last

    def _check_allowed(self) -> None:
        if self._login_rejected:
            raise ProviderAuthError(
                "the server rejected the login before: no new attempt until the "
                "credential is replaced or the account is verified"
            )
        wait = self._paused_until - self._clock()
        if wait > 0:
            raise ProviderUnavailableError(
                f"the mail server was unreachable: next attempt in {math.ceil(wait)}s"
            )

    def _pause(self) -> None:
        self._failures += 1
        pause = min(LONGEST_PAUSE, FIRST_PAUSE * 2 ** (self._failures - 1))
        self._paused_until = self._clock() + pause

    def _login(self) -> None:
        if self._auth == "xoauth2":
            token = self._credentials("access_token")
            self._session.login_oauth(self._username, token.get_secret_value())
        else:
            password = self._credentials("password")
            self._session.login(self._username, password.get_secret_value())
