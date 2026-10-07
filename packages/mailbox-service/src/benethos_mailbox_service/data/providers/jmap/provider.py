"""JMAP servers (RFC 8620, 8621): Fastmail, Stalwart, Cyrus (CONCEPT 5.6).

JSON over HTTPS. Ids are the server's own and stay when a message moves
(``STABLE_IDS``), and a message can be in several folders (``LABELS``).
The sync asks what changed since a state (``DELTA``), and the server's
event source tells when something did (``PUSH``).

Sending goes through JMAP too: the message is stored in the drafts folder,
submitted, and moved to the sent folder once the server took it
(RFC 8621 7). Without a sent folder no copy is kept.

The account signs in with a password (HTTP Basic, e.g. Stalwart or Cyrus)
or an API token (Bearer, e.g. Fastmail). The credential is decrypted for
each request and not kept.
"""

from __future__ import annotations

import base64
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import anyio

from ....common.chunks import batched
from ....common.clock import utc_now
from ....errors import (
    BadRequestError,
    ConflictError,
    MailboxServiceError,
    NotFoundError,
    NotSupportedError,
    ProviderError,
    ProviderUnavailableError,
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
from ...protocols import Pick, ServerClient, jmap
from .. import rules
from ..base import (
    Capability,
    ChangedMessage,
    CredentialReader,
    FolderChanges,
    ProviderSettings,
)
from . import mappers

# Message ids asked for at once while listing a whole folder.
QUERY_PAGE = 500
# Changes asked for at once (Email/changes).
MAX_CHANGES = 500
# The seconds between the pings of the event source, and how long a read
# waits for the next line before the stream counts as broken.
PING = 60
PING_WAIT = 2 * PING + 30
# The name and type a message's source is downloaded as.
SOURCE = ("message.eml", "message/rfc822")
WITH_SUBMISSION = (jmap.CORE, jmap.MAIL, jmap.SUBMISSION)


def settings_from(
    servers: list[MailServer], credential: CredentialKind, email: str
) -> dict[str, str | int | bool]:
    """The settings of a JMAP account from discovered servers, as
    ``JmapProvider`` reads them. Empty without a JMAP server."""
    server = rules.server_of(servers, ServerProtocol.JMAP)
    if server is None or credential is CredentialKind.OAUTH:
        return {}
    settings: dict[str, str | int | bool] = {
        "host": server.host,
        "port": server.port,
        "path": server.path or jmap.DEFAULT_PATH,
    }
    if credential is CredentialKind.API_TOKEN:
        settings["auth"] = "token"
    else:
        settings["username"] = server.username or email
    return settings


@dataclass(frozen=True)
class _Changes:
    """What changed in the account since a state: where each created or
    changed message is now, and which are gone."""

    state: str
    where: dict[str, frozenset[str]] = field(default_factory=dict)
    created: frozenset[str] = frozenset()
    destroyed: tuple[str, ...] = ()
    at: datetime | None = None


class JmapProvider:
    capabilities = frozenset(
        {
            Capability.SEND,
            Capability.DRAFTS,
            Capability.FLAGS,
            Capability.FOLDERS,
            Capability.SEARCH,
            Capability.SERVER_SEARCH,
            Capability.LABELS,
            Capability.STABLE_IDS,
            Capability.DELTA,
            Capability.PUSH,
        }
    )

    def __init__(
        self,
        settings: ProviderSettings,
        credentials: CredentialReader,
        *,
        pick: Pick | None = None,
        http: ServerClient | None = None,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = utc_now,
    ) -> None:
        """``pick`` checks the host of each request. ``http`` replaces the
        client, e.g. with a fake server."""
        host = settings.get("host")
        if not host:
            raise BadRequestError("a JMAP account needs settings.host")
        if str(settings.get("security", "tls")) != "tls":
            raise BadRequestError(
                "settings.security must be 'tls': JMAP runs over HTTPS"
            )
        path = str(settings.get("path") or jmap.DEFAULT_PATH)
        if not _is_path(path):
            raise BadRequestError(
                "settings.path must be a path such as /.well-known/jmap"
            )
        auth = settings.get("auth", "password")
        if auth not in ("password", "token"):
            raise BadRequestError("settings.auth must be 'password' or 'token'")
        username = settings.get("username")
        if auth == "password" and not username:
            raise BadRequestError(
                "a JMAP account with a password needs settings.username"
            )
        self._auth = str(auth)
        self._username = str(username or "")
        self._credentials = credentials
        server = jmap.JmapServer(
            host=str(host),
            port=rules.port_of(settings, "port", jmap.DEFAULT_PORT),
            path=path,
            pick=pick,
        )
        self._client = jmap.JmapClient(
            server,
            self._authorization,
            http=http or ServerClient(pick=pick),
            clock=clock,
        )
        self._now = now
        # The changes since one state, asked once for every folder of a pass.
        self._changes: tuple[str, _Changes] | None = None
        # The state of the account's emails the push last saw.
        self._pushed: str | None = None

    # --- the wire -------------------------------------------------------------------

    def _authorization(self) -> str:
        """The Authorization header, with the credential decrypted for this
        one request."""
        if self._auth == "token":
            return f"Bearer {self._credentials('token').get_secret_value()}"
        password = self._credentials("password").get_secret_value()
        pair = f"{self._username}:{password}".encode()
        return f"Basic {base64.b64encode(pair).decode()}"

    async def _account(self) -> str:
        return (await self._client.session()).account_id

    async def _call(
        self, *calls: jmap.Invocation, using: Iterable[str] = (jmap.CORE, jmap.MAIL)
    ) -> list[jmap.Invocation]:
        return await self._client.call(list(calls), using)

    async def _one(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        """One method call in a request of its own, its arguments."""
        account = await self._account()
        return jmap.result(
            await self._call((name, {"accountId": account, **args}, "0")), "0"
        )

    async def _emails(
        self, ids: list[str], properties: list[str]
    ) -> dict[str, dict[str, Any]]:
        """The emails among ``ids`` that are there, by id, in batches the
        server takes."""
        limit = (await self._client.session()).limit(
            "maxObjectsInGet", jmap.DEFAULT_GET
        )
        found: dict[str, dict[str, Any]] = {}
        for batch in batched([i for i in ids if mappers.is_id(i)], limit):
            got = await self._one("Email/get", {"ids": batch, "properties": properties})
            found.update((str(e["id"]), e) for e in got.get("list") or [])
        return found

    async def _email(self, message_id: str, properties: list[str]) -> dict[str, Any]:
        found = (await self._emails([message_id], properties)).get(message_id)
        if found is None:
            raise missing_message(message_id)
        return found

    # --- folders --------------------------------------------------------------------

    async def _mailboxes(self) -> list[dict[str, Any]]:
        got = await self._one(
            "Mailbox/get", {"ids": None, "properties": mappers.MAILBOX_PROPERTIES}
        )
        return list(got.get("list") or [])

    async def _role_id(self, role: FolderRole) -> str | None:
        for folder in await self.list_folders():
            if folder.role is role:
                return folder.id
        return None

    async def list_folders(self) -> list[Folder]:
        return [mappers.folder(m) for m in await self._mailboxes()]

    async def create_folder(self, name: str, parent_id: str | None) -> Folder:
        folders = await self.list_folders()
        _check_place(folders, None, name, parent_id)
        done = await self._one(
            "Mailbox/set",
            {
                "create": {
                    "new": {"name": name, "parentId": parent_id, "isSubscribed": True}
                }
            },
        )
        failed = (done.get("notCreated") or {}).get("new")
        if failed is not None:
            raise jmap.set_error(failed, "folder")
        # Asked for apart: not every server resolves a reference to a /set.
        made = str(((done.get("created") or {}).get("new") or {}).get("id"))
        got = await self._one(
            "Mailbox/get", {"ids": [made], "properties": mappers.MAILBOX_PROPERTIES}
        )
        found = got.get("list") or []
        if not found:
            raise ProviderError("the folder was stored but cannot be found again")
        return mappers.folder(found[0])

    async def update_folder(
        self, folder_id: str, name: str, parent_id: str | None
    ) -> Folder:
        folders = await self.list_folders()
        current = next((f for f in folders if f.id == folder_id), None)
        if current is None:
            raise missing("folder", folder_id)
        if current.name == name and current.parent_id == parent_id:
            return current
        _check_place(folders, folder_id, name, parent_id)
        account = await self._account()
        answers = await self._call(
            (
                "Mailbox/set",
                {
                    "accountId": account,
                    "update": {folder_id: {"name": name, "parentId": parent_id}},
                },
                "set",
            ),
            (
                "Mailbox/get",
                {
                    "accountId": account,
                    "ids": [folder_id],
                    "properties": mappers.MAILBOX_PROPERTIES,
                },
                "get",
            ),
        )
        failed = (jmap.result(answers, "set").get("notUpdated") or {}).get(folder_id)
        if failed is not None:
            raise jmap.set_error(failed, "folder")
        return _only_folder(answers, "get")

    async def delete_folder(self, folder_id: str) -> None:
        if not mappers.is_id(folder_id):
            raise missing("folder", folder_id)
        done = await self._one(
            "Mailbox/set", {"destroy": [folder_id], "onDestroyRemoveEmails": False}
        )
        failed = (done.get("notDestroyed") or {}).get(folder_id)
        if failed is not None:
            raise jmap.set_error(failed, "folder")

    # --- messages -------------------------------------------------------------------

    async def list_messages(
        self,
        folder_id: str | None,
        *,
        limit: int,
        cursor: str | None,
        search: MessageFilter | None = None,
    ) -> Page[MessageSummary]:
        """Without a folder: every folder of the account."""
        if folder_id is not None and not mappers.is_id(folder_id):
            raise missing("folder", folder_id)
        scope = mappers.scope(folder_id, search)
        query: dict[str, Any] = {
            "filter": mappers.query_filter(folder_id, search),
            "sort": mappers.SORT,
            # One more, to tell whether a next page follows.
            "limit": limit + 1,
        }
        start: tuple[str, int] | None = None
        if cursor:
            start = mappers.parse_cursor(cursor, scope)
            query.update(anchor=start[0], anchorOffset=1)
        answers = await self._page(query)
        if start is not None and jmap.error_type(answers, "q") == "anchorNotFound":
            # Gone since: the next one has moved up to its place.
            del query["anchor"], query["anchorOffset"]
            answers = await self._page({**query, "position": start[1]})
        found = jmap.result(answers, "q")
        emails = {str(e["id"]): e for e in jmap.result(answers, "g").get("list") or []}
        ids = [str(i) for i in found.get("ids") or []]
        page = ids[:limit]
        capped = found.get("limit")
        more = len(ids) > limit or (
            isinstance(capped, int) and 0 < capped <= limit and len(ids) >= capped
        )
        position = found.get("position")
        first = position if isinstance(position, int) else 0
        return Page[MessageSummary](
            items=[mappers.summary(emails[i]) for i in page if i in emails],
            next_cursor=mappers.cursor(scope, page[-1], first + len(page) - 1)
            if more and page
            else None,
        )

    async def _page(self, query: dict[str, Any]) -> list[jmap.Invocation]:
        """A page of a query and its emails, in one request."""
        account = await self._account()
        return await self._call(
            ("Email/query", {"accountId": account, **query}, "q"),
            (
                "Email/get",
                {
                    "accountId": account,
                    "#ids": {"resultOf": "q", "name": "Email/query", "path": "/ids"},
                    "properties": mappers.SUMMARY_PROPERTIES,
                },
                "g",
            ),
        )

    async def get_message(self, message_id: str) -> Message:
        email = await self._email(message_id, mappers.SUMMARY_PROPERTIES)
        return mappers.message(email, await self._source(email, message_id))

    async def get_attachment(
        self, message_id: str, attachment_id: str
    ) -> AttachmentContent:
        raw = await self.get_raw(message_id)
        return convert.attachment(parse.ParsedMessage(raw), attachment_id)

    async def get_raw(self, message_id: str) -> bytes:
        email = await self._email(message_id, ["blobId"])
        return await self._source(email, message_id)

    async def _source(self, email: dict[str, Any], message_id: str) -> bytes:
        try:
            return await self._client.download(str(email["blobId"]), *SOURCE)
        except NotFoundError:
            raise missing_message(message_id) from None

    # --- sending --------------------------------------------------------------------

    async def send(self, raw: bytes, sender: str, recipients: list[str]) -> SentMessage:
        """The recipients go in the envelope, Bcc among them: the source
        names none of those."""
        session = await self._client.session()
        if not session.offers(jmap.SUBMISSION):
            raise NotSupportedError("the JMAP server offers no sending for this login")
        folders = await self.list_folders()
        drafts = rules.role_folder(folders, FolderRole.DRAFTS)
        sent = rules.role_folder(folders, FolderRole.SENT)
        holder = drafts or sent
        if holder is None:
            raise ConflictError("the account has no drafts or sent folder to send from")
        identity = await self._identity(sender)
        blob = await self._client.upload(raw, SOURCE[1])
        keywords = {mappers.SEEN: True}
        if holder is drafts:
            keywords[mappers.DRAFT] = True
        submission: dict[str, Any] = {
            "accountId": session.account_id,
            "create": {
                "s": {
                    "identityId": identity,
                    "emailId": "#m",
                    "envelope": {
                        "mailFrom": {"email": sender},
                        "rcptTo": [{"email": r} for r in recipients],
                    },
                }
            },
        }
        if sent is None:
            submission["onSuccessDestroyEmail"] = ["#s"]
        elif holder is not sent:
            submission["onSuccessUpdateEmail"] = {
                "#s": {
                    f"mailboxIds/{holder.id}": None,
                    f"mailboxIds/{sent.id}": True,
                    f"keywords/{mappers.DRAFT}": None,
                }
            }
        answers = await self._call(
            (
                "Email/import",
                {
                    "accountId": session.account_id,
                    "emails": {
                        "m": {
                            "blobId": blob,
                            "mailboxIds": {holder.id: True},
                            "keywords": keywords,
                        }
                    },
                },
                "i",
            ),
            ("EmailSubmission/set", submission, "s"),
            using=WITH_SUBMISSION,
        )
        imported = jmap.result(answers, "i")
        refused = (imported.get("notCreated") or {}).get("m")
        if refused is not None:
            raise jmap.set_error(refused, "message")
        stored = (imported.get("created") or {}).get("m") or {}
        if not stored.get("id"):
            raise ProviderError("the JMAP server did not store the message to send")
        email_id = str(stored["id"])
        failed = _submission_failure(answers)
        if failed is not None:
            await self._forget(email_id)
            raise failed
        # Sent: from here on nothing may fail, or a client would send again.
        if sent is None:
            return SentMessage()
        try:
            copy = await self._email(email_id, mappers.SUMMARY_PROPERTIES)
        except MailboxServiceError as exc:
            return SentMessage(copy_error=exc.message)
        return SentMessage(sent_copy=mappers.summary(copy))

    async def _identity(self, sender: str) -> str:
        """The identity to send as: the one with the sender's address, else
        one for the sender's domain, else the first."""
        account = await self._account()
        answers = await self._call(
            ("Identity/get", {"accountId": account, "ids": None}, "0"),
            using=WITH_SUBMISSION,
        )
        identities = list(jmap.result(answers, "0").get("list") or [])
        if not identities:
            raise ConflictError("the JMAP account has no identity to send as")
        wanted = sender.lower()
        domain = "*@" + wanted.rpartition("@")[2]
        for match in (wanted, domain):
            for identity in identities:
                if str(identity.get("email") or "").lower() == match:
                    return str(identity["id"])
        return str(identities[0]["id"])

    async def _forget(self, email_id: str) -> None:
        """Remove a message that was stored to be sent and was not."""
        try:
            await self._one("Email/set", {"destroy": [email_id]})
        except MailboxServiceError:
            pass  # a stray draft is better than hiding why the send failed

    # --- drafts ---------------------------------------------------------------------

    async def _drafts_id(self) -> str:
        found = await self._role_id(FolderRole.DRAFTS)
        if found is None:
            raise rules.no_folder(FolderRole.DRAFTS)
        return found

    async def _draft(self, draft_id: str, drafts: str) -> None:
        """Only drafts: any other id is not found, so the draft operations
        reach no other mail."""
        found = (await self._emails([draft_id], ["mailboxIds"])).get(draft_id)
        if found is None or drafts not in (found.get("mailboxIds") or {}):
            raise missing("draft", draft_id)

    async def list_drafts(
        self, *, limit: int, cursor: str | None
    ) -> Page[MessageSummary]:
        return await self.list_messages(
            await self._drafts_id(), limit=limit, cursor=cursor
        )

    async def save_draft(self, raw: bytes, replaces: str | None) -> MessageSummary:
        drafts = await self._drafts_id()
        if replaces is not None:
            await self._draft(replaces, drafts)
        blob = await self._client.upload(raw, SOURCE[1])
        done = await self._one(
            "Email/import",
            {
                "emails": {
                    "d": {
                        "blobId": blob,
                        "mailboxIds": {drafts: True},
                        "keywords": {mappers.DRAFT: True, mappers.SEEN: True},
                    }
                }
            },
        )
        refused = (done.get("notCreated") or {}).get("d")
        if refused is not None:
            raise jmap.set_error(refused, "draft")
        made = str(((done.get("created") or {}).get("d") or {}).get("id"))
        stored = (await self._emails([made], mappers.SUMMARY_PROPERTIES)).get(made)
        if stored is None:
            raise ProviderError("the draft was stored but cannot be found again")
        if replaces is not None:
            await self._destroy(replaces, "draft", missing_ok=True)
        return mappers.summary(stored)

    async def get_draft(self, draft_id: str) -> bytes:
        await self._draft(draft_id, await self._drafts_id())
        return await self.get_raw(draft_id)

    async def delete_draft(self, draft_id: str) -> None:
        await self._draft(draft_id, await self._drafts_id())
        await self._destroy(draft_id, "draft")

    async def _destroy(
        self, email_id: str, what: str, missing_ok: bool = False
    ) -> None:
        done = await self._one("Email/set", {"destroy": [email_id]})
        failed = (done.get("notDestroyed") or {}).get(email_id)
        if failed is None or (missing_ok and failed.get("type") == "notFound"):
            return
        raise jmap.set_error(failed, what)

    # --- changing -------------------------------------------------------------------

    async def update_messages(
        self, message_ids: list[str], changes: MessageUpdate
    ) -> dict[str, MessageSummary | MailboxServiceError]:
        targets = None
        if changes.folder_ids is not None:
            rules.move_target(changes, self.capabilities)
            targets = list(dict.fromkeys(changes.folder_ids))
            known = {f.id for f in await self.list_folders()}
            unknown = next((t for t in targets if t not in known), None)
            if unknown is not None:
                return dict.fromkeys(message_ids, missing("folder", unknown))
        current = await self._emails(message_ids, ["keywords", "mailboxIds"])
        patches: dict[str, dict[str, Any]] = {}
        for message_id, email in current.items():
            patch = mappers.keyword_patch(email.get("keywords") or {}, changes)
            if targets is not None and set(targets) != set(
                email.get("mailboxIds") or {}
            ):
                patch["mailboxIds"] = dict.fromkeys(targets, True)
            if patch:
                patches[message_id] = patch
        return await self._changed(message_ids, current, patches)

    async def delete_messages(
        self, message_ids: list[str], permanent: bool
    ) -> dict[str, MessageSummary | None | MailboxServiceError]:
        if permanent:
            return await self._destroyed(message_ids)
        trash = await self._role_id(FolderRole.TRASH)
        if trash is None:
            return dict.fromkeys(message_ids, rules.no_folder(FolderRole.TRASH))
        current = await self._emails(message_ids, ["mailboxIds"])
        results: dict[str, MessageSummary | None | MailboxServiceError] = {}
        patches: dict[str, dict[str, Any]] = {}
        for message_id, email in current.items():
            if set(email.get("mailboxIds") or {}) == {trash}:
                results[message_id] = rules.in_trash_already()
            else:
                patches[message_id] = {"mailboxIds": {trash: True}}
        moved = await self._changed(
            [i for i in message_ids if i not in results], current, patches
        )
        results.update(moved)
        return {i: results[i] for i in message_ids}

    async def _changed(
        self,
        message_ids: list[str],
        current: dict[str, dict[str, Any]],
        patches: dict[str, dict[str, Any]],
    ) -> dict[str, MessageSummary | MailboxServiceError]:
        """Apply ``patches``, then each message as it is now, or why not."""
        results: dict[str, MessageSummary | MailboxServiceError] = {
            i: missing_message(i) for i in message_ids if i not in current
        }
        if patches:
            done = await self._one("Email/set", {"update": patches})
            for message_id, error in (done.get("notUpdated") or {}).items():
                results[str(message_id)] = _message_error(error, str(message_id))
        wanted = [i for i in message_ids if i not in results]
        now = await self._emails(wanted, mappers.SUMMARY_PROPERTIES)
        for message_id in wanted:
            email = now.get(message_id)
            results[message_id] = (
                mappers.summary(email) if email else missing_message(message_id)
            )
        return {i: results[i] for i in message_ids}

    async def _destroyed(
        self, message_ids: list[str]
    ) -> dict[str, MessageSummary | None | MailboxServiceError]:
        results: dict[str, MessageSummary | None | MailboxServiceError] = {
            i: missing_message(i) for i in message_ids if not mappers.is_id(i)
        }
        wanted = [i for i in message_ids if i not in results]
        if wanted:
            done = await self._one("Email/set", {"destroy": wanted})
            failed = done.get("notDestroyed") or {}
            for message_id in wanted:
                error = failed.get(message_id)
                results[message_id] = (
                    _message_error(error, message_id) if error is not None else None
                )
        return {i: results[i] for i in message_ids}

    # --- for the sync worker --------------------------------------------------------

    async def folder_states(self) -> dict[str, str]:
        """The counts stand in for a state. The sync asks every folder what
        changed since the account's state, whatever these say."""
        return {
            str(m["id"]): f"{m.get('totalEmails')}.{m.get('unreadEmails')}"
            for m in await self._mailboxes()
        }

    async def folder_contents(self, folder_id: str) -> list[str]:
        if not mappers.is_id(folder_id):
            raise missing("folder", folder_id)
        _, ids = await self._contents(folder_id)
        return ids

    async def _contents(self, folder_id: str) -> tuple[str, list[str]]:
        """The state of the account's emails, then the ids of every message
        in the folder. The state is read first: a message that arrives while
        the folder is read counts again with the next changes."""
        account = await self._account()
        query = {
            "accountId": account,
            "filter": {"inMailbox": folder_id},
            "sort": mappers.SORT,
            "limit": QUERY_PAGE,
        }
        answers = await self._call(
            ("Email/get", {"accountId": account, "ids": []}, "s"),
            ("Email/query", {**query, "position": 0}, "q"),
        )
        state = str(jmap.result(answers, "s").get("state") or "")
        ids: list[str] = []
        page = jmap.result(answers, "q")
        while True:
            found = [str(i) for i in page.get("ids") or []]
            ids += found
            if not found or (len(found) < QUERY_PAGE and "limit" not in page):
                return state, ids
            page = await self._one("Email/query", {**query, "position": len(ids)})

    async def message_headers(self, message_ids: list[str]) -> dict[str, str | None]:
        found = await self._emails(message_ids, ["messageId"])
        return {
            message_id: f"<{email['messageId'][0]}>" if email.get("messageId") else None
            for message_id, email in found.items()
        }

    async def flag_changes(
        self, folder_id: str, since: str, message_ids: list[str]
    ) -> list[str]:
        """JMAP reports changes since a state instead."""
        return []

    async def folder_changes(self, folder_id: str, token: str | None) -> FolderChanges:
        """The token is the state of the account's emails. JMAP tells what
        changed in the account, not in a folder: a message counts as changed
        in the folder it is in now and as removed from every other one, so a
        move shows as one. A deleted message is removed from every folder."""
        if not mappers.is_id(folder_id):
            raise missing("folder", folder_id)
        if token is None:
            state, ids = await self._contents(folder_id)
            return FolderChanges(state, [ChangedMessage(i) for i in ids])
        changes = await self._since(token)
        changed: list[ChangedMessage] = []
        removed = list(changes.destroyed)
        for message_id, folders in changes.where.items():
            if folder_id in folders:
                created = changes.at if message_id in changes.created else None
                changed.append(ChangedMessage(message_id, created))
            elif message_id not in changes.created:
                removed.append(message_id)
        return FolderChanges(changes.state, changed, removed)

    async def _since(self, token: str) -> _Changes:
        """What changed since ``token``, asked once for all folders of a
        pass: each asks with the same token."""
        if self._changes is not None and self._changes[0] == token:
            return self._changes[1]
        created: set[str] = set()
        updated: set[str] = set()
        destroyed: set[str] = set()
        state = token
        while True:
            found = await self._one(
                "Email/changes", {"sinceState": state, "maxChanges": MAX_CHANGES}
            )
            created |= {str(i) for i in found.get("created") or []}
            updated |= {str(i) for i in found.get("updated") or []}
            destroyed |= {str(i) for i in found.get("destroyed") or []}
            state = str(found.get("newState") or state)
            if not found.get("hasMoreChanges"):
                break
        # Created and gone again within the span: nothing to report.
        fleeting = created & destroyed
        destroyed -= fleeting
        where = await self._emails(
            sorted((created | updated) - destroyed - fleeting), ["mailboxIds"]
        )
        gone = (created | updated) - destroyed - fleeting - set(where)
        result = _Changes(
            state=state,
            where={i: frozenset(e.get("mailboxIds") or {}) for i, e in where.items()},
            # JMAP says which are new since the token. They count as created
            # now, the moment the sync learns of them.
            created=frozenset(created - fleeting),
            destroyed=tuple(sorted(destroyed | (gone - created))),
            at=self._now(),
        )
        self._changes = (token, result)
        return result

    async def wait_for_change(self, timeout: float) -> bool:
        """The event source, until the state of the account's emails moves
        on from the one the last wait saw."""
        account = await self._account()
        state = str((await self._one("Email/get", {"ids": []})).get("state") or "")
        if self._pushed is not None and state != self._pushed:
            self._pushed = state
            return True
        self._pushed = state
        with anyio.move_on_after(timeout):
            async with self._client.events("Email", PING, PING_WAIT) as changes:
                async for changed in changes:
                    now = (changed.get(account) or {}).get("Email")
                    if now and now != self._pushed:
                        self._pushed = str(now)
                        return True
            raise ProviderUnavailableError("the JMAP server closed its event stream")
        return False

    async def verify(self) -> None:
        """A fresh session, then one call: both need the credential."""
        session = await self._client.session(fresh=True)
        self._changes = None
        await self._one("Mailbox/get", {"ids": [], "properties": ["id"]})
        if not session.offers(jmap.MAIL):
            raise ProviderError("the server offers no JMAP mail for this login")

    async def close(self) -> None:
        await self._client.close()


def _is_path(path: str) -> bool:
    """A path on the server, with a query perhaps: printable ASCII without
    spaces, and no fragment."""
    return (
        path.startswith("/")
        and path.isascii()
        and path.isprintable()
        and " " not in path
        and "#" not in path
    )


def _check_place(
    folders: list[Folder], folder_id: str | None, name: str, parent_id: str | None
) -> None:
    """Refuse a folder ``name`` below ``parent_id`` where it cannot be: the
    parent is missing, is the folder itself or below it, or a folder of
    that name is there already."""
    by_id = {f.id: f for f in folders}
    if parent_id is not None:
        if parent_id not in by_id:
            raise missing("folder", parent_id)
        above: str | None = parent_id
        while above is not None:
            if above == folder_id:
                raise BadRequestError("a folder cannot move into itself")
            above = by_id[above].parent_id if above in by_id else None
    if any(
        f.parent_id == parent_id and f.name == name and f.id != folder_id
        for f in folders
    ):
        raise ConflictError(f"a folder {name} exists there already")


def _only_folder(answers: list[jmap.Invocation], tag: str) -> Folder:
    found = jmap.result(answers, tag).get("list") or []
    if not found:
        raise ProviderError("the folder was stored but cannot be found again")
    return mappers.folder(found[0])


def _message_error(error: dict[str, Any], message_id: str) -> MailboxServiceError:
    if error.get("type") == "notFound":
        return missing_message(message_id)
    return jmap.set_error(error, "message")


def _submission_failure(answers: list[jmap.Invocation]) -> MailboxServiceError | None:
    """Why the server did not take the message, None when it did."""
    try:
        submitted = jmap.result(answers, "s")
    except MailboxServiceError as exc:
        return exc
    refused = (submitted.get("notCreated") or {}).get("s")
    if refused is not None:
        return jmap.set_error(refused, "message")
    if "s" not in (submitted.get("created") or {}):
        return ProviderError("the JMAP server did not say whether it sent the message")
    return None
