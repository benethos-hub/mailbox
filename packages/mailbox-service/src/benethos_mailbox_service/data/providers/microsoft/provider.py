"""Microsoft 365 and Outlook.com over Microsoft Graph (CONCEPT 5.4).

Every call carries the account's access token from its ``TokenSource`` and
asks for immutable ids, so a message keeps its id when it moves
(``STABLE_IDS``). A refused token is renewed once. If it is refused
again, the account needs a new sign-in.

Sending and drafts go as MIME, composed by ``data.mail.compose`` like for
any other provider: ``sendMail`` sends and keeps the copy in Sent Items, a
draft is created from MIME and replaced by creating a new one. Graph cannot
change a draft's MIME in place.

Details Graph's documentation leaves open are marked **(unverified)**
until a live check against a Microsoft account confirms them. Seen live:
search results come under ids that change on a move, despite the
preference. The adapter looks their immutable ids up.
"""

from __future__ import annotations

import base64
import math
import time
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import quote, unquote, urlencode, urlsplit

from ....errors import (
    BadRequestError,
    ConflictError,
    MailboxServiceError,
    NotFoundError,
    NotSupportedError,
    ProviderAuthError,
    ProviderError,
    ProviderUnavailableError,
)
from ...http import Answer, ApiClient
from ...mail import compose, convert
from ...mail.parse import ParsedMessage
from ...models import (
    AttachmentContent,
    Folder,
    FolderRole,
    Message,
    MessageFilter,
    MessageSummary,
    MessageUpdate,
    Page,
    SentMessage,
)
from .. import rules
from ..base import Capability, TokenSource
from . import mappers

GRAPH = "https://graph.microsoft.com"
VERSION = "/v1.0"
# A page of folders or of message ids, as many as Graph hands out at once.
PAGE_SIZE = 250
# Requests in one JSON batch, Graph's limit.
BATCH_SIZE = 20
# Ids that survive a move (CONCEPT 4.1), asked for on every request.
IMMUTABLE_IDS = 'IdType="ImmutableId"'


class MicrosoftProvider:
    capabilities = frozenset(
        {
            Capability.SEND,
            Capability.DRAFTS,
            Capability.SERVER_SEARCH,
            Capability.STABLE_IDS,
        }
    )

    def __init__(
        self,
        tokens: TokenSource,
        http: ApiClient | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._tokens = tokens
        self._http = http or ApiClient()
        self._clock = clock
        self._roles: dict[str, FolderRole] | None = None
        self._root: str | None = None
        # Until when Graph asked to be left alone (Retry-After).
        self._rest_until = 0.0

    # --- the wire -------------------------------------------------------------------

    async def _call(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
        json_body: Any = None,
        content: bytes | None = None,
        content_type: str | None = None,
    ) -> Answer:
        """One Graph request. ``path`` below ``/v1.0``, e.g. ``/me/messages``.
        While Graph asked to be left alone, nothing is sent."""
        wait = self._rest_until - self._clock()
        if wait > 0:
            raise ProviderUnavailableError(
                f"microsoft asked to wait: next attempt in {math.ceil(wait)}s"
            )
        for attempt in (1, 2):
            token = await self._tokens.access_token()
            headers = {
                "Authorization": f"Bearer {token.get_secret_value()}",
                "Prefer": IMMUTABLE_IDS,
            }
            if content_type:
                headers["Content-Type"] = content_type
            answer = await self._http.request(
                method,
                f"{GRAPH}{VERSION}{path}",
                headers=headers,
                params=params,
                json_body=json_body,
                content=content,
            )
            if answer.status == 401 and attempt == 1:
                # Revoked or changed since it was issued: one more try with
                # a new one.
                self._tokens.reject()
                continue
            if not answer.ok:
                self._rest_until = self._clock() + _retry_after(answer)
                raise _failure(answer)
            return answer
        raise AssertionError("unreachable")  # pragma: no cover

    async def _json(self, method: str, path: str, **kwargs: Any) -> Any:
        return (await self._call(method, path, **kwargs)).json()

    async def _all(self, path: str, params: Mapping[str, str]) -> list[dict[str, Any]]:
        """Every item of a list, following Graph's pages."""
        items: list[dict[str, Any]] = []
        body = await self._json("GET", path, params=params)
        while True:
            items.extend(body.get("value") or [])
            link = body.get("@odata.nextLink")
            if not link:
                return items
            body = await self._json("GET", _own_path(link))

    # --- folders --------------------------------------------------------------------

    async def _folder_roles(self) -> dict[str, FolderRole]:
        """The id of each well-known folder the mailbox has, and its role."""
        if self._roles is None:
            roles: dict[str, FolderRole] = {}
            for name, role in mappers.WELL_KNOWN.items():
                try:
                    found = await self._json(
                        "GET", f"/me/mailFolders/{name}", params={"$select": "id"}
                    )
                except NotFoundError:
                    continue
                roles[str(found["id"])] = role
            self._roles = roles
        return self._roles

    async def _role_id(self, role: FolderRole) -> str:
        for folder_id, found in (await self._folder_roles()).items():
            if found is role:
                return folder_id
        raise rules.no_folder(role)

    async def list_folders(self) -> list[Folder]:
        roles = await self._folder_roles()
        params = {"$select": mappers.FOLDER_FIELDS, "$top": str(PAGE_SIZE)}
        found: list[Folder] = []
        waiting = await self._all("/me/mailFolders", params)
        while waiting:
            item = waiting.pop(0)
            found.append(mappers.folder(item, roles))
            if item.get("childFolderCount"):
                waiting.extend(
                    await self._all(
                        f"/me/mailFolders/{_id(item['id'])}/childFolders", params
                    )
                )
        return found

    async def create_folder(self, name: str, parent_id: str | None) -> Folder:
        path = (
            f"/me/mailFolders/{_id(parent_id)}/childFolders"
            if parent_id
            else "/me/mailFolders"
        )
        item = await self._json("POST", path, json_body={"displayName": name})
        return mappers.folder(item, await self._folder_roles())

    async def update_folder(
        self, folder_id: str, name: str, parent_id: str | None
    ) -> Folder:
        path = f"/me/mailFolders/{_id(folder_id)}"
        item = await self._json("PATCH", path, json_body={"displayName": name})
        # The top of the folder tree is the mailbox's root folder, which
        # Graph names as the parent of a top-level folder.
        root = await self._root_id()
        if (item.get("parentFolderId") or root) != (parent_id or root):
            item = await self._json(
                "POST", f"{path}/move", json_body={"destinationId": parent_id or root}
            )
        return mappers.folder(item, await self._folder_roles())

    async def _root_id(self) -> str:
        if self._root is None:
            item = await self._json("GET", "/me/mailFolders/msgfolderroot")
            self._root = str(item["id"])
        return self._root

    async def delete_folder(self, folder_id: str) -> None:
        await self._call("DELETE", f"/me/mailFolders/{_id(folder_id)}")

    # --- messages -------------------------------------------------------------------

    async def list_messages(
        self,
        folder_id: str | None,
        *,
        limit: int,
        cursor: str | None,
        search: MessageFilter | None = None,
    ) -> Page[MessageSummary]:
        query, rest = mappers.query(search)
        if cursor:
            body = await self._json("GET", _own_path(cursor))
        else:
            path = (
                f"/me/mailFolders/{_id(folder_id)}/messages"
                if folder_id
                else "/me/messages"
            )
            params = {"$select": mappers.SUMMARY_FIELDS, "$top": str(limit), **query}
            body = await self._json("GET", path, params=params)
        found = body.get("value") or []
        if "$search" in query or (cursor and "search=" in unquote(cursor)):
            found = await self._immutable(found)
        items = [mappers.summary(item) for item in found]
        link = body.get("@odata.nextLink")
        return Page[MessageSummary](
            items=[item for item in items if mappers.keeps(item, rest)],
            next_cursor=_own_path(link) if link else None,
        )

    async def _immutable(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Search results under their immutable ids.

        Seen live: Graph's search ignores the preference for immutable ids,
        a message fetched by such an id comes back under it again, and
        ``translateExchangeIds`` is refused for personal accounts. A list
        filtered by ``internetMessageId`` does answer with immutable ids:
        so each result is looked up by its Message-ID, twenty to a JSON
        batch, in the folder it was found in. One that cannot be looked
        up keeps the id the search gave.
        """
        ids: dict[str, str] = {}
        wanted = [item for item in items if item.get("internetMessageId")]
        for start in range(0, len(wanted), BATCH_SIZE):
            chunk = wanted[start : start + BATCH_SIZE]
            requests = []
            for n, item in enumerate(chunk):
                header = str(item["internetMessageId"]).replace("'", "''")
                query = urlencode(
                    {
                        "$select": "id,parentFolderId",
                        "$filter": f"internetMessageId eq '{header}'",
                    }
                )
                requests.append(
                    {
                        "id": str(n),
                        "method": "GET",
                        "url": f"/me/messages?{query}",
                        "headers": {"Prefer": IMMUTABLE_IDS},
                    }
                )
            answer = await self._json(
                "POST", "/$batch", json_body={"requests": requests}
            )
            for reply in answer.get("responses") or []:
                if reply.get("status") != 200:
                    continue
                item = chunk[int(reply["id"])]
                found = (reply.get("body") or {}).get("value") or []
                same = [
                    f
                    for f in found
                    if f.get("parentFolderId") == item.get("parentFolderId")
                ]
                if len(same) == 1:
                    ids[item["id"]] = str(same[0]["id"])
        return [{**item, "id": ids.get(item["id"], item["id"])} for item in items]

    async def get_message(self, message_id: str) -> Message:
        path = f"/me/messages/{_id(message_id)}"
        item = await self._json("GET", path, params={"$select": mappers.MESSAGE_FIELDS})
        attachments: list[dict[str, Any]] = []
        if item.get("hasAttachments"):
            attachments = await self._all(
                f"{path}/attachments",
                {"$select": "id,name,contentType,size,isInline"},
            )
        found = mappers.message(item, attachments)
        if item.get("isDraft"):
            # What a draft answers lives in its MIME only.
            thread = convert.thread_fields(
                ParsedMessage(await self.get_raw(message_id))
            )
            found = found.model_copy(
                update={k: thread[k] for k in ("reference", "in_reply_to")}
            )
        return found

    async def get_attachment(
        self, message_id: str, attachment_id: str
    ) -> AttachmentContent:
        path = f"/me/messages/{_id(message_id)}/attachments/{_id(attachment_id)}"
        item = await self._json("GET", path)
        content = item.get("contentBytes")
        data = (
            base64.b64decode(content)
            if content
            else (await self._call("GET", f"{path}/$value")).body
        )
        return mappers.attachment_content(item, data)

    async def get_raw(self, message_id: str) -> bytes:
        return (await self._call("GET", f"/me/messages/{_id(message_id)}/$value")).body

    async def send(self, raw: bytes, sender: str, recipients: list[str]) -> SentMessage:
        """Graph takes the recipients from the MIME headers, and keeps the
        copy in Sent Items itself. Recipients the headers do not name are
        the Bcc ones: they go in a Bcc header, which Exchange takes out
        before delivery **(unverified)**."""
        await self._call(
            "POST",
            "/me/sendMail",
            content=base64.b64encode(compose.with_bcc(raw, recipients)),
            content_type="text/plain",
        )
        return SentMessage()

    # --- drafts ---------------------------------------------------------------------

    async def list_drafts(
        self, *, limit: int, cursor: str | None
    ) -> Page[MessageSummary]:
        drafts = await self._role_id(FolderRole.DRAFTS)
        return await self.list_messages(drafts, limit=limit, cursor=cursor)

    async def save_draft(self, raw: bytes, replaces: str | None) -> MessageSummary:
        if replaces is not None:
            await self._draft(replaces)
        item = await self._json(
            "POST",
            "/me/messages",
            content=base64.b64encode(raw),
            content_type="text/plain",
        )
        if replaces is not None:
            await self._delete_for_good(replaces)
        return mappers.summary(item)

    async def get_draft(self, draft_id: str) -> bytes:
        await self._draft(draft_id)
        return await self.get_raw(draft_id)

    async def delete_draft(self, draft_id: str) -> None:
        await self._draft(draft_id)
        await self._delete_for_good(draft_id)

    async def _draft(self, draft_id: str) -> None:
        """Only drafts: any other id is not found, so the draft operations
        reach no other mail."""
        try:
            item = await self._json(
                "GET", f"/me/messages/{_id(draft_id)}", params={"$select": "isDraft"}
            )
        except BadRequestError:
            item = {}
        if not item.get("isDraft"):
            raise NotFoundError(f"draft {draft_id} not found")

    # --- changing -------------------------------------------------------------------

    async def update_messages(
        self, message_ids: list[str], changes: MessageUpdate
    ) -> dict[str, MessageSummary | MailboxServiceError]:
        body = mappers.changes(changes.unread, changes.starred, changes.keywords)

        async def one(message_id: str) -> MessageSummary:
            # Judged per id, as the other adapters answer it.
            target = rules.move_target(changes, self.capabilities)
            path = f"/me/messages/{_id(message_id)}"
            item = None
            if body:
                item = await self._json("PATCH", path, json_body=body)
            if target is not None:
                item = await self._json(
                    "POST", f"{path}/move", json_body={"destinationId": target}
                )
            if item is None:
                item = await self._json(
                    "GET", path, params={"$select": mappers.SUMMARY_FIELDS}
                )
            return mappers.summary(item)

        return await rules.per_id(message_ids, one)

    async def delete_messages(
        self, message_ids: list[str], permanent: bool
    ) -> dict[str, MessageSummary | None | MailboxServiceError]:
        try:
            trash = await self._role_id(FolderRole.TRASH)
        except ConflictError as exc:
            return dict.fromkeys(message_ids, exc)

        async def one(message_id: str) -> MessageSummary | None:
            if permanent:
                await self._delete_for_good(message_id, trash)
                return None
            path = f"/me/messages/{_id(message_id)}"
            where = await self._json("GET", path, params={"$select": "parentFolderId"})
            if where.get("parentFolderId") == trash:
                raise rules.in_trash_already()
            item = await self._json(
                "POST", f"{path}/move", json_body={"destinationId": trash}
            )
            return mappers.summary(item)

        return await rules.per_id(message_ids, one)

    async def _delete_for_good(self, message_id: str, trash: str | None = None) -> None:
        """Graph's DELETE outside the trash only moves the message there.
        For good means: into the trash, then deleted from it."""
        if trash is None:
            trash = await self._role_id(FolderRole.TRASH)
        path = f"/me/messages/{_id(message_id)}"
        where = await self._json("GET", path, params={"$select": "parentFolderId"})
        if where.get("parentFolderId") != trash:
            item = await self._json(
                "POST", f"{path}/move", json_body={"destinationId": trash}
            )
            path = f"/me/messages/{_id(str(item['id']))}"
        await self._call("DELETE", path)

    # --- for the sync worker ------------------------------------------------------
    # Ids are stable: the domain keeps no id mapping for this provider, so
    # these serve checks such as "is the folder empty".

    async def folder_states(self) -> dict[str, str]:
        """Graph reports no UIDNEXT: the counts stand in. A message that
        arrives read while another leaves goes unnoticed until the next
        change, which the sync then catches up on."""
        return {f.id: f"{f.total}:{f.unread}" for f in await self.list_folders()}

    async def folder_contents(self, folder_id: str) -> list[str]:
        items = await self._all(
            f"/me/mailFolders/{_id(folder_id)}/messages",
            {"$select": "id", "$top": str(PAGE_SIZE)},
        )
        return [str(item["id"]) for item in items]

    async def flag_changes(
        self, folder_id: str, since: str, message_ids: list[str]
    ) -> list[str]:
        """Graph reports changes through delta queries instead."""
        return []

    async def message_headers(self, message_ids: list[str]) -> dict[str, str | None]:
        """Twenty to a JSON batch. A message that is gone is left out."""
        found: dict[str, str | None] = {}
        for start in range(0, len(message_ids), BATCH_SIZE):
            chunk = message_ids[start : start + BATCH_SIZE]
            requests = [
                {
                    "id": str(n),
                    "method": "GET",
                    "url": f"/me/messages/{_id(message_id)}?$select=internetMessageId",
                    "headers": {"Prefer": IMMUTABLE_IDS},
                }
                for n, message_id in enumerate(chunk)
            ]
            answer = await self._json(
                "POST", "/$batch", json_body={"requests": requests}
            )
            for reply in answer.get("responses") or []:
                if reply.get("status") != 200:
                    continue
                body = reply.get("body") or {}
                found[chunk[int(reply["id"])]] = body.get("internetMessageId")
        return found

    async def wait_for_change(self, timeout: float) -> bool:
        """No push yet: Graph's change notifications need a public endpoint
        (CONCEPT 5.4)."""
        raise NotSupportedError("Microsoft accounts are polled, not pushed")

    async def verify(self) -> None:
        self._roles = None
        await self._call("GET", "/me/mailFolders/inbox", params={"$select": "id"})

    async def close(self) -> None:
        await self._http.close()


def _id(value: str | None) -> str:
    """An id as one part of a path."""
    return quote(str(value), safe="")


def _own_path(link: str) -> str:
    """The path of a Graph link, e.g. a next page, below ``/v1.0``. Refuses
    any other host: a cursor comes back from the caller, and a forged one
    must not carry the token elsewhere."""
    parts = urlsplit(link)
    if (parts.scheme or parts.netloc) and f"{parts.scheme}://{parts.netloc}" != GRAPH:
        raise BadRequestError("invalid cursor")
    # A full link names the version, but a cursor handed out before does not.
    rest = parts.path.removeprefix(VERSION) if parts.netloc else parts.path
    if not rest.startswith("/me/") or ".." in rest:
        raise BadRequestError("invalid cursor")
    return f"{rest}?{parts.query}" if parts.query else rest


def _retry_after(answer: Answer) -> float:
    """The seconds Graph asks to wait, 0 when it asks nothing."""
    if answer.status not in (429, 503):
        return 0.0
    value = answer.headers.get("retry-after", "")
    return float(value) if value.isdigit() else 0.0


def _failure(answer: Answer) -> MailboxServiceError:
    """Graph's error as this project's, with Graph's code and message."""
    try:
        error = (answer.json() or {}).get("error") or {}
    except ProviderError:
        error = {}
    code = error.get("code") or answer.status
    text = f"microsoft: {error.get('message') or 'request failed'} ({code})"
    if answer.status == 401:
        return ProviderAuthError("microsoft refused the access token: sign in again")
    if answer.status == 404:
        return NotFoundError(text)
    if answer.status == 409:
        return ConflictError(text)
    if answer.status == 400:
        return BadRequestError(text)
    if answer.status in (429, 502, 503, 504):
        wait = answer.headers.get("retry-after")
        later = f", retry after {wait}s" if wait else ""
        return ProviderUnavailableError(f"microsoft is busy{later} ({code})")
    return ProviderError(text)
