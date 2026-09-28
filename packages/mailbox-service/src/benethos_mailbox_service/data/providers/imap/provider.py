"""The IMAP adapter: one account, one connection, one lock.

IMAP connections are stateful (the selected folder), so every operation runs
as one uninterrupted sequence under the account's lock, in a worker thread.
The credential is decrypted right before a login and not kept.

Towards the server the adapter is careful (CONCEPT 5.9): ``Guard`` paces
the requests, blocks a rejected login and pauses an unreachable server.
"""

from __future__ import annotations

import itertools
import threading
import time
from collections.abc import Callable
from functools import partial
from typing import Any, TypeVar

import anyio

from .... import __version__
from ....common.chunks import batched
from ....common.ratelimit import Clock, Sleep
from ....errors import (
    BadRequestError,
    ConflictError,
    MailboxServiceError,
    NotFoundError,
    NotSupportedError,
    ProviderError,
    missing,
    missing_message,
)
from ...mail import convert, parse
from ...models import (
    AttachmentContent,
    CredentialKind,
    Folder,
    FolderRole,
    MailServer,
    Message,
    MessageFilter,
    MessageSummary,
    MessageUpdate,
    Page,
    SentMessage,
    ServerProtocol,
)
from ...protocols import (
    IMAP_PORTS,
    ImapSession,
    Pick,
    SearchCriteria,
    Server,
    SmtpSession,
)
from .. import rules
from ..base import Capability, CredentialReader, FolderChanges, ProviderSettings
from ..guard import Guard
from ..sender import SmtpFactory, SmtpSender
from . import mappers

T = TypeVar("T")

SessionFactory = Callable[[Server], ImapSession]

CLIENT_ID = ("benethos-mailbox-service", __version__)

# A cautious default for servers nobody has told us about.
DEFAULT_REQUESTS_PER_MINUTE = 60

PROBE_TIMEOUT = 10.0

# Message-ID headers fetched per request during a sync.
HEADER_BATCH = 200


def default_session(server: Server) -> ImapSession:
    return ImapSession(server, client_id=CLIENT_ID)


def settings_from(
    servers: list[MailServer], credential: CredentialKind, email: str
) -> dict[str, str | int | bool]:
    """The settings of an IMAP account from discovered servers, as
    ``ImapProvider`` reads them. Empty without an IMAP server."""
    imap = next((s for s in servers if s.protocol is ServerProtocol.IMAP), None)
    if imap is None:
        return {}
    settings: dict[str, str | int | bool] = {
        "host": imap.host,
        "port": imap.port,
        "security": str(imap.security),
        "username": imap.username or email,
        "auth": "xoauth2" if credential is CredentialKind.OAUTH else "password",
    }
    smtp = next((s for s in servers if s.protocol is ServerProtocol.SMTP), None)
    if smtp is not None:
        settings["smtp_host"] = smtp.host
        settings["smtp_port"] = smtp.port
        settings["smtp_security"] = str(smtp.security)
        if smtp.username and smtp.username != settings["username"]:
            settings["smtp_username"] = smtp.username
    return settings


def probe_session(server: Server) -> ImapSession:
    return ImapSession(server, timeout=PROBE_TIMEOUT)


async def probe(
    host: str,
    port: int,
    security: str,
    address: str | None = None,
    session_factory: SessionFactory = probe_session,
) -> frozenset[str]:
    """The capabilities of an IMAP server, read without logging in. With
    ``address``, the connection goes there, the address just checked."""
    if security not in IMAP_PORTS:
        raise BadRequestError("IMAP without encryption is not supported")
    pick = (lambda _host, _port: address) if address is not None else None
    session = session_factory(
        Server(host=host, port=port, security=security, pick=pick)
    )
    return await anyio.to_thread.run_sync(session.read_capabilities)


class ImapProvider:
    # PUSH needs IDLE, which wait_for_change finds out after the login.
    capabilities = frozenset(
        {Capability.SERVER_SEARCH, Capability.PUSH, Capability.DRAFTS}
    )

    def __init__(
        self,
        settings: ProviderSettings,
        credentials: CredentialReader,
        session_factory: SessionFactory = default_session,
        clock: Clock = time.monotonic,
        sleep: Sleep = time.sleep,
        jitter: Callable[[float, float], float] | None = None,
        smtp_factory: SmtpFactory = SmtpSession,
        pick: Pick | None = None,
    ) -> None:
        """``pick`` checks the host of each connection, IMAP and SMTP."""
        host = settings.get("host")
        if not host:
            raise BadRequestError("an IMAP account needs settings.host")
        security = rules.encrypted(settings, "security", "IMAP")
        username = settings.get("username")
        if not username:
            raise BadRequestError("an IMAP account needs settings.username")
        auth = settings.get("auth", "password")
        if auth == "xoauth2":
            # Nothing renews the access token yet (CONCEPT 5.1): the login
            # would be rejected within the hour.
            raise NotSupportedError(
                "IMAP with OAuth (settings.auth 'xoauth2') is not supported yet: "
                "the service cannot renew the token. Use a password or an app "
                "password."
            )
        if auth != "password":
            raise BadRequestError("settings.auth must be 'password'")
        self._server = Server(
            host=str(host),
            port=rules.port_of(settings, "port", IMAP_PORTS[security]),
            security=security,
            pick=pick,
        )
        self._username = str(username)

        self._credentials = credentials
        per_minute = rules.rate_of(
            settings, "max_requests_per_minute", DEFAULT_REQUESTS_PER_MINUTE
        )
        self._guard = Guard(per_minute, clock=clock, sleep=sleep, jitter=jitter)
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
        # The folders as listed once in the current step, see _role_folder.
        self._folders: list[Folder] | None = None
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
        search: MessageFilter | None = None,
    ) -> Page[MessageSummary]:
        return await self._run(
            lambda: self._list_messages(folder_id, limit, cursor, search)
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
                "the account has no SMTP server: its settings name no smtp_host"
            )
        refused = await anyio.to_thread.run_sync(
            self._smtp.send, raw, sender, recipients
        )
        # Sent: from here on nothing may fail, or a client would send again.
        try:
            copy = await self._run(lambda: self._store_sent(raw))
        except MailboxServiceError as exc:
            return SentMessage(refused=refused, copy_error=exc.message)
        return SentMessage(refused=refused, sent_copy=copy)

    async def list_drafts(
        self, *, limit: int, cursor: str | None
    ) -> Page[MessageSummary]:
        return await self._run(lambda: self._list_drafts(limit, cursor))

    async def save_draft(self, raw: bytes, replaces: str | None) -> MessageSummary:
        return await self._retrying(
            lambda retried: self._save_draft(raw, replaces, retried=retried)
        )

    async def get_draft(self, draft_id: str) -> bytes:
        return await self._run(lambda: self._get_draft(draft_id))

    async def delete_draft(self, draft_id: str) -> None:
        await self._run(lambda: self._delete_draft(draft_id))

    async def create_folder(self, name: str, parent_id: str | None) -> Folder:
        return await self._retrying(
            lambda retried: self._create_folder(name, parent_id, retried)
        )

    async def update_folder(
        self, folder_id: str, name: str, parent_id: str | None
    ) -> Folder:
        return await self._retrying(
            lambda retried: self._update_folder(folder_id, name, parent_id, retried)
        )

    async def delete_folder(self, folder_id: str) -> None:
        await self._retrying(lambda retried: self._delete_folder(folder_id, retried))

    async def update_messages(
        self, message_ids: list[str], changes: MessageUpdate
    ) -> dict[str, MessageSummary | MailboxServiceError]:
        return await self._per_folder(
            message_ids,
            lambda folder, validity, uids, _: self._update_in_folder(
                folder, validity, uids, changes
            ),
        )

    async def delete_messages(
        self, message_ids: list[str], permanent: bool
    ) -> dict[str, MessageSummary | None | MailboxServiceError]:
        return await self._per_folder(
            message_ids,
            lambda folder, validity, uids, retried: self._delete_in_folder(
                folder, validity, uids, permanent, retried
            ),
        )

    async def _per_folder(
        self,
        message_ids: list[str],
        work: Callable[[str, int, list[int], bool], dict[int, T | MailboxServiceError]],
    ) -> dict[str, T | MailboxServiceError]:
        """Run ``work`` once per folder, each under the lock. A failure of
        the connection or the login stops everything. Any other failure
        answers for that folder's messages only."""
        folders, unknown = _by_folder(message_ids)
        results: dict[str, T | MailboxServiceError] = dict(unknown)
        for (folder, validity), by_uid in folders.items():
            try:
                done = await self._retrying(
                    partial(work, folder, validity, list(by_uid))
                )
            except rules.FATAL:
                raise
            except MailboxServiceError as exc:
                done = dict.fromkeys(by_uid, exc)
            for uid, outcome in done.items():
                results[by_uid[uid]] = outcome
        return results

    async def folder_states(self) -> dict[str, str]:
        return await self._run(self._folder_states)

    async def folder_contents(self, folder_id: str) -> list[str]:
        return await self._run(lambda: self._folder_contents(folder_id))

    async def flag_changes(
        self, folder_id: str, since: str, message_ids: list[str]
    ) -> list[str]:
        return await self._run(
            lambda: self._flag_changes(folder_id, since, message_ids)
        )

    async def message_headers(self, message_ids: list[str]) -> dict[str, str | None]:
        # Ids that are no id of this adapter are left out, like messages
        # that are gone.
        folders, _ = _by_folder(message_ids)
        found: dict[str, str | None] = {}
        for (folder, validity), by_uid in folders.items():
            uids = list(by_uid)
            # One request per batch, so a long first sync never holds the
            # connection for long.
            for batch in batched(uids, HEADER_BATCH):
                found.update(
                    await self._run(
                        partial(self._message_headers, folder, validity, batch)
                    )
                )
        return found

    async def folder_changes(self, folder_id: str, token: str | None) -> FolderChanges:
        raise NotSupportedError("IMAP folders are compared by their state")

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
        search: MessageFilter | None = None,
    ) -> Page[MessageSummary]:
        folder = mappers.folder_name(folder_id) if folder_id else mappers.INBOX
        before: int | None = None
        expected_validity: int | None = None
        if cursor:
            cursor_folder, expected_validity, before = mappers.parse_cursor(cursor)
            if cursor_folder != folder:
                raise rules.invalid_cursor()
        validity = self._session.select(folder)
        if expected_validity is not None and expected_validity != validity:
            raise BadRequestError("the folder changed on the server: start again")
        uids = self._session.search(_criteria(search or MessageFilter(), before))
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
            raise missing_message(message_id)
        return folder, validity, uid

    def _fetch(self, message_id: str) -> tuple[Any, str, int]:
        folder, validity, uid = self._select_message(message_id)
        message = self._session.fetch_message(uid)
        if message is None:
            raise missing_message(message_id)
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
        return self._append(sent, raw, ["\\Seen"])

    def _append(
        self, folder: str, raw: bytes, flags: list[str]
    ) -> MessageSummary | None:
        """Store ``raw`` in ``folder``. The stored message, found by its UID
        from APPENDUID or else by its Message-ID. None if neither finds it.

        A message with this Message-ID that the folder holds already is
        that stored message: the guard retries a step whose connection
        dropped, and the APPEND may have gone through before the drop."""
        header = parse.ParsedMessage(raw).message_id
        validity = self._session.select(folder)
        stored = self._session.search_message_id(header) if header else []
        uid = stored[-1] if stored else self._session.append(folder, raw, flags)
        if uid is None:
            validity = self._session.select(folder)
            matches = self._session.search_message_id(header) if header else []
            uid = matches[-1] if matches else None
        found = self._session.fetch_headers([uid]) if uid else []
        return mappers.to_summary(found[0], folder, validity) if found else None

    # --- drafts ---------------------------------------------------------------------

    def _list_drafts(self, limit: int, cursor: str | None) -> Page[MessageSummary]:
        drafts = mappers.folder_id(self._drafts_folder())
        return self._list_messages(drafts, limit, cursor)

    def _save_draft(
        self, raw: bytes, replaces: str | None, *, retried: bool = False
    ) -> MessageSummary:
        drafts = self._drafts_folder()
        # Checked before the new one is stored: a wrong id changes nothing.
        old = self._draft_place(replaces, drafts) if replaces else None
        if old is not None and not retried:
            # A retried step may have removed it already, after it stored
            # the new one, which _append then finds by its Message-ID.
            validity, uid = old
            found, _ = self._open_writable(drafts, validity, [uid])
            if uid not in found:
                raise missing("draft", replaces)
        saved = self._append(drafts, raw, ["\\Draft", "\\Seen"])
        if saved is None:
            raise ProviderError("the draft was stored but cannot be found again")
        if old is not None:
            try:
                self._delete_draft_at(drafts, *old)
            except NotFoundError:
                pass  # gone already: a retried step removed it before the drop
        return saved

    def _get_draft(self, draft_id: str) -> bytes:
        self._draft_place(draft_id, self._drafts_folder())
        return self._get_raw(draft_id)

    def _delete_draft(self, draft_id: str) -> None:
        drafts = self._drafts_folder()
        self._delete_draft_at(drafts, *self._draft_place(draft_id, drafts))

    def _delete_draft_at(self, drafts: str, validity: int, uid: int) -> None:
        found, _ = self._open_writable(drafts, validity, [uid])
        if uid not in found:
            raise missing("draft")
        self._session.expunge([uid])

    def _drafts_folder(self) -> str:
        drafts = self._role_folder(FolderRole.DRAFTS)
        if drafts is None:
            raise rules.no_folder(FolderRole.DRAFTS)
        return drafts

    def _draft_place(self, draft_id: str, drafts: str) -> tuple[int, int]:
        """UIDVALIDITY and UID of a draft id. Not found unless it names a
        message in the drafts folder."""
        absent = missing("draft", draft_id)
        try:
            folder, validity, uid = mappers.parse_message_id(draft_id)
        except NotFoundError:
            raise absent from None
        if folder != drafts:
            raise absent
        return validity, uid

    # --- folders --------------------------------------------------------------------

    def _create_folder(
        self, name: str, parent_id: str | None, retried: bool = False
    ) -> Folder:
        raws = self._session.list_folders()
        full = self._full_name(raws, name, parent_id)
        if full in _names(raws):
            if retried:
                return self._folder(full)  # the first try made it
            raise ConflictError(f"a folder {name} exists there already")
        self._session.create_folder(full)
        return self._folder(full)

    def _update_folder(
        self, folder_id: str, name: str, parent_id: str | None, retried: bool = False
    ) -> Folder:
        raws = self._session.list_folders()
        old = mappers.folder_name(folder_id)
        if old not in _names(raws):
            new = self._full_name(raws, name, parent_id)
            if retried and new in _names(raws):
                return self._folder(new)  # the first try renamed it
            raise missing("folder", folder_id)
        new = self._full_name(raws, name, parent_id)
        if new == old:
            return self._folder(old)
        if new in _names(raws):
            raise ConflictError(f"a folder {name} exists there already")
        if new.startswith(old + (self._delimiter(raws) or "\0")):
            raise BadRequestError("a folder cannot move into itself")
        self._session.rename_folder(old, new)
        return self._folder(new)

    def _delete_folder(self, folder_id: str, retried: bool = False) -> None:
        name = mappers.folder_name(folder_id)
        if name not in _names(self._session.list_folders()):
            if retried:
                return  # the first try deleted it
            raise missing("folder", folder_id)
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
            raise missing("folder", parent_id)
        if not delimiter:
            raise NotSupportedError("the mail server has no folder hierarchy")
        return parent + delimiter + name

    def _delimiter(self, raws: list[Any]) -> str | None:
        found = next((raw.delimiter for raw in raws if raw.delimiter), None)
        return found or self._session.personal_namespace()[1]

    def _role_folder(self, role: FolderRole) -> str | None:
        """The server's name of the folder with ``role``, if there is one.
        The folders are listed once per step: a draft save asks for the
        drafts folder several times."""
        if self._folders is None:
            self._folders = self._list_folders()
        return next(
            (mappers.folder_name(f.id) for f in self._folders if f.role is role),
            None,
        )

    def _folder(self, name: str) -> Folder:
        """A folder as listed, with its role and subscription."""
        for folder in self._list_folders(subscriptions=True):
            if folder.id == mappers.folder_id(name):
                return folder
        raise missing("folder", name)

    # --- changing messages, one folder at a time ------------------------------------

    def _update_in_folder(
        self, folder: str, validity: int, uids: list[int], changes: MessageUpdate
    ) -> dict[int, MessageSummary | MailboxServiceError]:
        """One folder's share of an update: one SELECT, one STORE per set
        of flag changes, one MOVE."""
        found, permanent = self._open_writable(folder, validity, uids)
        results = _missing(uids, found)
        if not found:
            return results
        target = self._move_target(changes, folder)
        plans: dict[tuple[tuple[str, ...], tuple[str, ...]], list[int]] = {}
        for uid, message in found.items():
            add, remove = mappers.flag_changes(message.flags, changes, permanent)
            if add or remove:
                plans.setdefault((tuple(add), tuple(remove)), []).append(uid)
        for (to_add, to_remove), plan_uids in plans.items():
            self._session.store_flags(plan_uids, list(to_add), list(to_remove))
        if plans:
            stored = list(found)
            found = {int(m.uid): m for m in self._session.fetch_headers(stored)}
            # Expunged by another client between the two fetches.
            results.update(_missing(stored, found))
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
        self,
        folder: str,
        validity: int,
        uids: list[int],
        permanent: bool,
        retried: bool = False,
    ) -> dict[int, MessageSummary | None | MailboxServiceError]:
        found, _ = self._open_writable(folder, validity, uids)
        results: dict[int, MessageSummary | None | MailboxServiceError] = dict(
            _missing(uids, found)
        )
        if retried:
            # Gone from the folder: the first try deleted or moved them,
            # to a place this try cannot name.
            results = {uid: None for uid in results}
        if not found:
            return results
        if permanent:
            self._session.expunge(list(found))
            results.update({uid: None for uid in found})
            return results
        trash = self._role_folder(FolderRole.TRASH)
        if trash is None:
            raise rules.no_folder(FolderRole.TRASH)
        if trash == folder:
            raise rules.in_trash_already()
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
            header = message.message_id
            if uid not in new_uids and header and _searchable(header):
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

    def _move_target(self, changes: MessageUpdate, current: str) -> str | None:
        """The folder to move to, or None to stay."""
        wanted = rules.move_target(changes, self.capabilities)
        if wanted is None:
            return None
        target = mappers.folder_name(wanted)
        if target == current:
            return None
        if target not in _names(self._session.list_folders()):
            raise missing("folder", wanted)
        return target

    def _get_raw(self, message_id: str) -> bytes:
        _, _, uid = self._select_message(message_id)
        raw = self._session.fetch_raw(uid)
        if raw is None:
            raise missing_message(message_id)
        return raw

    def _folder_states(self) -> dict[str, str]:
        """``UIDVALIDITY.UIDNEXT.MESSAGES``, with CONDSTORE also
        ``.HIGHESTMODSEQ``, so that a flag change changes the state too."""
        modseq = "CONDSTORE" in self._session.server_capabilities()
        self._session.noop()
        states = {}
        for folder in self._list_folders():
            validity, uidnext, count, highest = self._session.folder_state(
                mappers.folder_name(folder.id), modseq=modseq
            )
            state = f"{validity}.{uidnext}.{count}"
            states[folder.id] = state if highest is None else f"{state}.{highest}"
        return states

    def _flag_changes(
        self, folder_id: str, since: str, message_ids: list[str]
    ) -> list[str]:
        """Only with CONDSTORE, and only while the folder keeps its UIDs."""
        parts = since.split(".")
        if len(parts) != 4 or not all(p.isdigit() for p in parts):
            return []
        folder = mappers.folder_name(folder_id)
        validity = int(parts[0])
        by_uid = _by_folder(message_ids)[0].get((folder, validity), {})
        if not by_uid or self._session.select(folder) != validity:
            return []
        changed = self._session.changed_since(sorted(by_uid), int(parts[3]))
        return [by_uid[uid] for uid in changed if uid in by_uid]

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
            except MailboxServiceError:
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

    async def _retrying(self, operation: Callable[[bool], T]) -> T:
        """``_run`` for a write the guard may run again. ``operation``
        learns whether this is a retry, so that finding its work done
        counts as done, not as a conflict or a missing item."""
        attempts = itertools.count()
        return await self._run(lambda: operation(next(attempts) > 0))

    def _locked(self, operation: Callable[[], T]) -> T:
        def step() -> T:
            self._folders = None
            if not self._session.connected:
                self._login(self._session)
            return operation()

        with self._lock:
            return self._guard.attempts(step, drop=self._session.logout)

    def _secret(self) -> str:
        """The credential for the login, decrypted for this one use."""
        return self._credentials("password").get_secret_value()

    def _login(self, session: ImapSession) -> None:
        session.login(self._username, self._secret())


def _by_folder(
    message_ids: list[str],
) -> tuple[dict[tuple[str, int], dict[int, str]], dict[str, NotFoundError]]:
    """The ids by folder and UIDVALIDITY, as UID -> id, and those that are
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
) -> dict[int, MessageSummary | MailboxServiceError]:
    """``NotFoundError`` for every UID the folder no longer holds."""
    return {uid: missing_message() for uid in uids if uid not in found}


def _criteria(search: MessageFilter, before_uid: int | None) -> SearchCriteria:
    """The API's filter as IMAP SEARCH keys."""
    return SearchCriteria(
        text=search.text,
        sender=search.sender,
        to=search.to,
        subject=search.subject,
        since=search.after,
        before=search.before,
        unread=search.unread,
        flagged=search.starred,
        mixed=search.has_attachments,
        before_uid=before_uid,
    )


def _searchable(header: str) -> bool:
    """Whether a SEARCH can carry the Message-ID: a sender may write any
    bytes there, and imaplib writes commands in printable ASCII. Without
    it the next sync follows the moved message."""
    return header.isascii() and header.isprintable()
