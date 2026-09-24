"""The IMAP adapter: one account, one connection, one lock.

IMAP connections are stateful (the selected folder), so every operation runs
as one uninterrupted sequence under the account's lock, in a worker thread.
The credential is decrypted right before a login and not kept.

Towards the server the adapter is careful (CONCEPT 5.9): ``Guard`` paces
the requests, blocks a rejected login and pauses an unreachable server.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from functools import partial
from typing import Any, TypeVar

import anyio

from .... import __version__
from ....errors import (
    BadRequestError,
    ConflictError,
    MailboxApiError,
    NotFoundError,
    NotSupportedError,
    ProviderAuthError,
    ProviderUnavailableError,
)
from ...mail import convert
from ...mail.parse import ParsedMessage
from ...models import (
    AttachmentContent,
    Folder,
    FolderRole,
    Message,
    MessageSummary,
    MessageUpdate,
    Page,
    SentMessage,
)
from ..base import Capability, CredentialReader
from ..guard import Guard
from ..protocols.imap import ImapServer, ImapSession, SearchCriteria
from ..protocols.smtp import SmtpSession
from ..ratelimit import Clock, Sleep
from ..sender import SmtpFactory, SmtpSender
from . import mappers

T = TypeVar("T")

log = logging.getLogger(__name__)
R = TypeVar("R")

SessionFactory = Callable[[ImapServer], ImapSession]

DEFAULT_PORTS = {"tls": 993, "starttls": 143}

CLIENT_ID = ("benethos-mailbox-api", __version__)

# A cautious default for servers nobody has told us about.
DEFAULT_REQUESTS_PER_MINUTE = 60

PROBE_TIMEOUT = 10.0

# Message-ID headers fetched per request during a sync.
HEADER_BATCH = 200


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
    # PUSH needs IDLE, which wait_for_change finds out after the login.
    capabilities = frozenset({Capability.SERVER_SEARCH, Capability.PUSH})

    def __init__(
        self,
        settings: Any,
        credentials: CredentialReader,
        session_factory: SessionFactory = default_session,
        clock: Clock = time.monotonic,
        sleep: Sleep = time.sleep,
        jitter: Callable[[float, float], float] | None = None,
        smtp_factory: SmtpFactory = SmtpSession,
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
        per_minute = float(
            settings.get("max_requests_per_minute") or DEFAULT_REQUESTS_PER_MINUTE
        )
        self._guard = Guard(per_minute, clock=clock, sleep=sleep, jitter=jitter)
        self._smtp = SmtpSender.from_settings(
            settings,
            self._username,
            self._auth,
            self._secret,
            self._guard,
            smtp_factory,
        )
        if self._smtp is not None:
            self.capabilities = self.capabilities | {Capability.SEND}
        self._session = session_factory(self._server)
        self._lock = threading.Lock()
        # IDLE blocks its connection, so it gets one of its own.
        self._idle_session = session_factory(self._server)
        self._idle_lock = threading.Lock()
        self._closing = threading.Event()

    # --- MailProvider ---------------------------------------------------------

    async def list_folders(self) -> list[Folder]:
        return await self._run(lambda: self._list_folders(subscriptions=True))

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

    async def send(self, raw: bytes, sender: str, recipients: list[str]) -> SentMessage:
        if self._smtp is None:
            raise ConflictError(
                "the account has no SMTP server: set settings.smtp_host with "
                "PATCH /v1/accounts/{account_id}"
            )
        refused = await anyio.to_thread.run_sync(
            self._smtp.send, raw, sender, recipients
        )
        # Sent: from here on nothing may fail, or a client would send again.
        copy = None
        try:
            copy = await self._run(lambda: self._store_sent(raw))
        except MailboxApiError as exc:
            log.warning("sent, but no copy in the sent folder: %s", exc.message)
        return SentMessage(refused=refused, sent_copy=copy)

    async def create_folder(self, name: str, parent_id: str | None) -> Folder:
        return await self._run(lambda: self._create_folder(name, parent_id))

    async def update_folder(
        self, folder_id: str, name: str, parent_id: str | None
    ) -> Folder:
        return await self._run(lambda: self._update_folder(folder_id, name, parent_id))

    async def delete_folder(self, folder_id: str) -> None:
        await self._run(lambda: self._delete_folder(folder_id))

    async def update_messages(
        self, message_ids: list[str], changes: MessageUpdate
    ) -> dict[str, MessageSummary | MailboxApiError]:
        return await self._per_folder(
            message_ids,
            lambda folder, validity, uids: self._update_in_folder(
                folder, validity, uids, changes
            ),
        )

    async def delete_messages(
        self, message_ids: list[str], permanent: bool
    ) -> dict[str, MessageSummary | None | MailboxApiError]:
        return await self._per_folder(
            message_ids,
            lambda folder, validity, uids: self._delete_in_folder(
                folder, validity, uids, permanent
            ),
        )

    async def _per_folder(
        self,
        message_ids: list[str],
        work: Callable[[str, int, list[int]], dict[int, R | MailboxApiError]],
    ) -> dict[str, R | MailboxApiError]:
        """Run ``work`` once per folder, each under the lock. A failure of
        the connection or the login stops everything; any other failure
        answers for that folder's messages only."""
        folders, unknown = _by_folder(message_ids)
        results: dict[str, R | MailboxApiError] = dict(unknown)
        for (folder, validity), by_uid in folders.items():
            try:
                done = await self._run(partial(work, folder, validity, list(by_uid)))
            except (ProviderAuthError, ProviderUnavailableError):
                raise
            except MailboxApiError as exc:
                done = dict.fromkeys(by_uid, exc)
            for uid, outcome in done.items():
                results[by_uid[uid]] = outcome
        return results

    async def folder_states(self) -> dict[str, str]:
        return await self._run(self._folder_states)

    async def folder_contents(self, folder_id: str) -> list[str]:
        return await self._run(lambda: self._folder_contents(folder_id))

    async def message_headers(self, message_ids: list[str]) -> dict[str, str | None]:
        folders, unknown = _by_folder(message_ids)
        if unknown:
            raise next(iter(unknown.values()))
        found: dict[str, str | None] = {}
        for (folder, validity), by_uid in folders.items():
            uids = list(by_uid)
            # One request per batch, so a long first sync never holds the
            # connection for long.
            for start in range(0, len(uids), HEADER_BATCH):
                batch = uids[start : start + HEADER_BATCH]
                found.update(
                    await self._run(
                        partial(self._message_headers, folder, validity, batch)
                    )
                )
        return found

    async def wait_for_change(self, timeout: float) -> bool:
        return await anyio.to_thread.run_sync(
            self._wait_for_change, timeout, abandon_on_cancel=True
        )

    async def verify(self) -> None:
        await anyio.to_thread.run_sync(self._verify)

    async def close(self) -> None:
        self._closing.set()
        await anyio.to_thread.run_sync(self._close)

    # --- the sequences, each under the lock -------------------------------------

    def _list_folders(self, subscriptions: bool = False) -> list[Folder]:
        return mappers.to_folders(self._session.list_folders(subscriptions))

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

    def _select_message(self, message_id: str) -> tuple[str, int, int]:
        """Select the message's folder: its folder, UIDVALIDITY and UID."""
        folder, validity, uid = mappers.parse_message_id(message_id)
        if self._session.select(folder) != validity:
            raise NotFoundError(f"message {message_id} not found")
        return folder, validity, uid

    def _fetch(self, message_id: str) -> tuple[Any, str, int]:
        folder, validity, uid = self._select_message(message_id)
        message = self._session.fetch_message(uid)
        if message is None:
            raise NotFoundError(f"message {message_id} not found")
        return message, folder, validity

    def _get_message(self, message_id: str) -> Message:
        message, folder, validity = self._fetch(message_id)
        return mappers.to_message(message, folder, validity)

    def _get_attachment(self, message_id: str, attachment_id: str) -> AttachmentContent:
        message, _, _ = self._fetch(message_id)
        return convert.attachment(message, attachment_id)

    # --- sending ---------------------------------------------------------------------

    def _store_sent(self, raw: bytes) -> MessageSummary | None:
        """A read copy in the folder with the sent role, as mail clients do.
        None where the account has no such folder."""
        sent = self._role_folder(FolderRole.SENT)
        if sent is None:
            return None
        uid = self._session.append(sent, raw, ["\\Seen"])
        validity = self._session.select(sent)
        if uid is None:
            header = convert.message_id_header(ParsedMessage(raw))
            matches = self._session.search_message_id(header) if header else []
            uid = matches[-1] if matches else None
        found = self._session.fetch_headers([uid]) if uid else []
        return mappers.to_summary(found[0], sent, validity) if found else None

    # --- folders --------------------------------------------------------------------

    def _create_folder(self, name: str, parent_id: str | None) -> Folder:
        raws = self._session.list_folders()
        full = self._full_name(raws, name, parent_id)
        if full in _names(raws):
            raise ConflictError(f"a folder {name} exists there already")
        self._session.create_folder(full)
        return self._folder(full)

    def _update_folder(
        self, folder_id: str, name: str, parent_id: str | None
    ) -> Folder:
        raws = self._session.list_folders()
        old = mappers.folder_name(folder_id)
        if old not in _names(raws):
            raise NotFoundError(f"folder {folder_id} not found")
        new = self._full_name(raws, name, parent_id)
        if new == old:
            return self._folder(old)
        if new in _names(raws):
            raise ConflictError(f"a folder {name} exists there already")
        if new.startswith(old + (self._delimiter(raws) or "\0")):
            raise BadRequestError("a folder cannot move into itself")
        self._session.rename_folder(old, new)
        return self._folder(new)

    def _delete_folder(self, folder_id: str) -> None:
        name = mappers.folder_name(folder_id)
        if name not in _names(self._session.list_folders()):
            raise NotFoundError(f"folder {folder_id} not found")
        self._session.delete_folder(name)

    def _full_name(self, raws: list[Any], name: str, parent_id: str | None) -> str:
        """The server's name for ``name`` below ``parent_id``, or at the top
        of the user's personal namespace."""
        delimiter = self._delimiter(raws)
        if delimiter and delimiter in name:
            raise BadRequestError(
                f"a folder name cannot contain {delimiter!r}: use parent_id"
            )
        if parent_id is None:
            prefix, _ = self._session.personal_namespace()
            return prefix + name
        parent = mappers.folder_name(parent_id)
        if parent not in _names(raws):
            raise NotFoundError(f"folder {parent_id} not found")
        if not delimiter:
            raise NotSupportedError("the mail server has no folder hierarchy")
        return parent + delimiter + name

    def _delimiter(self, raws: list[Any]) -> str | None:
        found = next((raw.delimiter for raw in raws if raw.delimiter), None)
        return found or self._session.personal_namespace()[1]

    def _role_folder(self, role: FolderRole) -> str | None:
        """The server's name of the folder with ``role``, if there is one."""
        return next(
            (mappers.folder_name(f.id) for f in self._list_folders() if f.role is role),
            None,
        )

    def _folder(self, name: str) -> Folder:
        """A folder as listed, with its role and subscription."""
        for folder in self._list_folders(subscriptions=True):
            if folder.id == mappers.folder_id(name):
                return folder
        raise NotFoundError(f"folder {name} not found")

    # --- changing messages, one folder at a time ------------------------------------

    def _update_in_folder(
        self, folder: str, validity: int, uids: list[int], changes: MessageUpdate
    ) -> dict[int, MessageSummary | MailboxApiError]:
        """One folder's share of an update: one SELECT, one STORE per set
        of flag changes, one MOVE."""
        found, permanent = self._open_writable(folder, validity, uids)
        results = _missing(uids, found)
        if not found:
            return results
        target = self._move_target(changes.folder_ids, folder)
        plans: dict[tuple[tuple[str, ...], tuple[str, ...]], list[int]] = {}
        for uid, message in found.items():
            add, remove = mappers.flag_changes(message.flags, changes, permanent)
            if add or remove:
                plans.setdefault((tuple(add), tuple(remove)), []).append(uid)
        for (to_add, to_remove), plan_uids in plans.items():
            self._session.store_flags(plan_uids, list(to_add), list(to_remove))
        if plans:
            found = {int(m.uid): m for m in self._session.fetch_headers(list(found))}
        if target is None:
            results.update(
                {
                    uid: mappers.to_summary(m, folder, validity)
                    for uid, m in found.items()
                }
            )
            return results
        moved = self._move(found, target)
        for uid, message in found.items():
            # Not found in the target at once: the next sync follows it.
            results[uid] = moved.get(uid) or mappers.to_summary(
                message, folder, validity
            ).model_copy(update={"folder_ids": [mappers.folder_id(target)]})
        return results

    def _delete_in_folder(
        self, folder: str, validity: int, uids: list[int], permanent: bool
    ) -> dict[int, MessageSummary | None | MailboxApiError]:
        found, _ = self._open_writable(folder, validity, uids)
        results: dict[int, MessageSummary | None | MailboxApiError] = dict(
            _missing(uids, found)
        )
        if not found:
            return results
        if permanent:
            self._session.expunge(list(found))
            results.update({uid: None for uid in found})
            return results
        trash = self._role_folder(FolderRole.TRASH)
        if trash is None:
            raise ConflictError(
                "the account has no trash folder: delete with permanent=true"
            )
        if trash == folder:
            raise ConflictError(
                "the message is in the trash already: delete with permanent=true"
            )
        moved = self._move(found, trash)
        results.update({uid: moved.get(uid) for uid in found})
        return results

    def _open_writable(
        self, folder: str, validity: int, uids: list[int]
    ) -> tuple[dict[int, Any], frozenset[str]]:
        """Select a folder read-write and fetch the headers of ``uids``.
        None found when the folder was renumbered."""
        current, permanent = self._session.select_writable(folder)
        if current != validity:
            return {}, permanent
        found = {int(m.uid): m for m in self._session.fetch_headers(uids)}
        return found, permanent

    def _move(self, found: dict[int, Any], target: str) -> dict[int, MessageSummary]:
        """Move messages of the selected folder with one command. Their
        summaries in ``target``, for those found there at once."""
        new_uids = self._session.move(list(found), target)
        target_validity = self._session.select(target)
        for uid, message in found.items():
            header = convert.message_id_header(message)
            if uid not in new_uids and header:
                # No COPYUID: find it by its Message-ID, if that is unambiguous.
                matches = self._session.search_message_id(header)
                if len(matches) == 1:
                    new_uids[uid] = matches[0]
        fetched = {
            int(m.uid): m for m in self._session.fetch_headers(list(new_uids.values()))
        }
        return {
            uid: mappers.to_summary(fetched[new], target, target_validity)
            for uid, new in new_uids.items()
            if new in fetched
        }

    def _move_target(self, folder_ids: list[str] | None, current: str) -> str | None:
        """The folder to move to, or None to stay."""
        if folder_ids is None:
            return None
        if len(set(folder_ids)) != 1:
            raise BadRequestError("an IMAP message is in exactly one folder")
        target = mappers.folder_name(folder_ids[0])
        if target == current:
            return None
        if target not in _names(self._session.list_folders()):
            raise NotFoundError(f"folder {folder_ids[0]} not found")
        return target

    def _get_raw(self, message_id: str) -> bytes:
        _, _, uid = self._select_message(message_id)
        raw = self._session.fetch_raw(uid)
        if raw is None:
            raise NotFoundError(f"message {message_id} not found")
        return raw

    def _folder_states(self) -> dict[str, str]:
        states = {}
        for folder in self._list_folders():
            validity, uidnext, count = self._session.folder_state(
                mappers.folder_name(folder.id)
            )
            states[folder.id] = f"{validity}.{uidnext}.{count}"
        return states

    def _folder_contents(self, folder_id: str) -> list[str]:
        folder = mappers.folder_name(folder_id)
        validity = self._session.select(folder)
        return [
            mappers.message_id(folder, validity, uid)
            for uid in self._session.search(SearchCriteria())
        ]

    def _message_headers(
        self, folder: str, validity: int, uids: list[int]
    ) -> dict[str, str | None]:
        if self._session.select(folder) != validity:
            return {}  # renumbered: these ids are gone
        return {
            mappers.message_id(folder, validity, uid): header
            for uid, header in self._session.fetch_message_ids(uids).items()
        }

    def _wait_for_change(self, timeout: float) -> bool:
        """IDLE on the inbox, over a connection of its own so requests are
        not held up."""
        with self._idle_lock:
            if self._closing.is_set():
                return False
            self._guard.check()
            session = self._idle_session
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
            except MailboxApiError:
                session.logout()
                raise

    def _verify(self) -> None:
        with self._lock:
            self._guard.reset()
            self._session.logout()
            with self._guard.refused_logins():
                self._login(self._session)
                if self._smtp is not None:
                    self._smtp.verify()

    def _close(self) -> None:
        with self._lock:
            self._session.logout()
        # Waits for a running IDLE to notice ``_closing``, at most IDLE_STEP.
        with self._idle_lock:
            self._idle_session.logout()

    # --- plumbing ---------------------------------------------------------------

    async def _run(self, operation: Callable[[], T]) -> T:
        return await anyio.to_thread.run_sync(self._locked, operation)

    def _locked(self, operation: Callable[[], T]) -> T:
        def step() -> T:
            if not self._session.connected:
                self._login(self._session)
            return operation()

        with self._lock:
            return self._guard.attempts(step, drop=self._session.logout)

    def _secret(self) -> str:
        """The credential for the login, decrypted for this one use."""
        field = "access_token" if self._auth == "xoauth2" else "password"
        return self._credentials(field).get_secret_value()

    def _login(self, session: ImapSession) -> None:
        if self._auth == "xoauth2":
            session.login_oauth(self._username, self._secret())
        else:
            session.login(self._username, self._secret())


def _by_folder(
    message_ids: list[str],
) -> tuple[dict[tuple[str, int], dict[int, str]], dict[str, NotFoundError]]:
    """The ids by folder and UIDVALIDITY, as UID -> id; and those that are
    no id of this adapter."""
    folders: dict[tuple[str, int], dict[int, str]] = {}
    unknown: dict[str, NotFoundError] = {}
    for message_id in message_ids:
        try:
            folder, validity, uid = mappers.parse_message_id(message_id)
        except NotFoundError as exc:
            unknown[message_id] = exc
            continue
        folders.setdefault((folder, validity), {})[uid] = message_id
    return folders, unknown


def _names(raws: list[Any]) -> set[str]:
    """The server's names of listed folders."""
    return {raw.name for raw in raws}


def _missing(
    uids: list[int], found: dict[int, Any]
) -> dict[int, MessageSummary | MailboxApiError]:
    """``NotFoundError`` for every UID the folder no longer holds."""
    return {uid: NotFoundError("message not found") for uid in uids if uid not in found}
