"""Microsoft 365 and Outlook.com over Microsoft Graph (CONCEPT 5.4).

Every call carries the account's access token from its ``TokenSource`` and
asks for immutable ids, so a message keeps its id when it moves
(``STABLE_IDS``). A refused token is renewed once; refused again, the
account needs a new sign-in.

Sending and drafts go as MIME, composed by ``data.mail.compose`` like for
any other provider: ``sendMail`` sends and keeps the copy in Sent Items, a
draft is created from MIME and replaced by creating a new one. Graph cannot
change a draft's MIME in place.

Details Graph's documentation leaves open are marked **(unverified)**
until a live check against a Microsoft account confirms them.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping
from email.parser import BytesHeaderParser
from email.policy import default
from email.utils import getaddresses
from typing import Any
from urllib.parse import quote, urlsplit

from ....errors import (
    BadRequestError,
    ConflictError,
    MailboxApiError,
    NotFoundError,
    ProviderAuthError,
    ProviderError,
    ProviderUnavailableError,
)
from ...http import Answer, ApiClient
from ...mail import compose
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
from ..base import Capability, TokenSource
from . import mappers

GRAPH = "https://graph.microsoft.com"
VERSION = "/v1.0"
# A page of folders or of message ids, as many as Graph hands out at once.
BATCH = 250


class MicrosoftProvider:
    capabilities = frozenset(
        {
            Capability.SEND,
            Capability.DRAFTS,
            Capability.SERVER_SEARCH,
            Capability.STABLE_IDS,
        }
    )

    def __init__(self, tokens: TokenSource, http: ApiClient | None = None) -> None:
        self._tokens = tokens
        self._http = http or ApiClient()
        self._roles: dict[str, FolderRole] | None = None

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
        """One Graph request. ``path`` below ``/v1.0``, e.g. ``/me/messages``."""
        for attempt in (1, 2):
            token = await self._tokens.access_token()
            headers = {
                "Authorization": f"Bearer {token.get_secret_value()}",
                "Prefer": 'IdType="ImmutableId"',
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
        raise NotFoundError(f"the mailbox has no {role} folder")

    async def list_folders(self) -> list[Folder]:
        roles = await self._folder_roles()
        params = {"$select": mappers.FOLDER_FIELDS, "$top": str(BATCH)}
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
        if item.get("parentFolderId") != parent_id:
            # The top of the folder tree is the mailbox's root folder.
            target = parent_id or "msgfolderroot"
            item = await self._json(
                "POST", f"{path}/move", json_body={"destinationId": target}
            )
        return mappers.folder(item, await self._folder_roles())

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
        items = [mappers.summary(item) for item in body.get("value") or []]
        link = body.get("@odata.nextLink")
        return Page[MessageSummary](
            items=[item for item in items if mappers.keeps(item, rest)],
            next_cursor=_own_path(link) if link else None,
        )

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
            headers = BytesHeaderParser(policy=default).parsebytes(
                await self.get_raw(message_id)
            )
            found = found.model_copy(
                update={
                    "reference": compose.read_reference(
                        headers.get(compose.REFERENCE_HEADER)
                    ),
                    "in_reply_to": headers.get("In-Reply-To"),
                }
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
        return AttachmentContent(
            filename=item.get("name") or None,
            content_type=item.get("contentType") or "application/octet-stream",
            data=data,
        )

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
            content=base64.b64encode(_with_bcc(raw, recipients)),
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
            await self._call("DELETE", f"/me/messages/{_id(replaces)}")
        return mappers.summary(item)

    async def get_draft(self, draft_id: str) -> bytes:
        await self._draft(draft_id)
        return await self.get_raw(draft_id)

    async def delete_draft(self, draft_id: str) -> None:
        await self._draft(draft_id)
        await self._call("DELETE", f"/me/messages/{_id(draft_id)}")

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
    ) -> dict[str, MessageSummary | MailboxApiError]:
        body = mappers.changes(changes.unread, changes.starred, changes.keywords)
        target = changes.folder_ids[0] if changes.folder_ids else None
        results: dict[str, MessageSummary | MailboxApiError] = {}
        for message_id in message_ids:
            path = f"/me/messages/{_id(message_id)}"
            try:
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
                results[message_id] = mappers.summary(item)
            except (ProviderAuthError, ProviderUnavailableError):
                raise
            except MailboxApiError as exc:
                results[message_id] = exc
        return results

    async def delete_messages(
        self, message_ids: list[str], permanent: bool
    ) -> dict[str, MessageSummary | None | MailboxApiError]:
        trash = None if permanent else await self._role_id(FolderRole.TRASH)
        results: dict[str, MessageSummary | None | MailboxApiError] = {}
        for message_id in message_ids:
            path = f"/me/messages/{_id(message_id)}"
            try:
                if trash is None:
                    await self._call("DELETE", path)
                    results[message_id] = None
                    continue
                where = await self._json(
                    "GET", path, params={"$select": "parentFolderId"}
                )
                if where.get("parentFolderId") == trash:
                    raise ConflictError(
                        "the message is in the trash already: delete with "
                        "permanent=true"
                    )
                item = await self._json(
                    "POST", f"{path}/move", json_body={"destinationId": trash}
                )
                results[message_id] = mappers.summary(item)
            except (ProviderAuthError, ProviderUnavailableError):
                raise
            except MailboxApiError as exc:
                results[message_id] = exc
        return results

    # --- for the sync worker ------------------------------------------------------
    # Ids are stable: the domain keeps no id mapping for this provider, so
    # these serve checks such as "is the folder empty".

    async def folder_states(self) -> dict[str, str]:
        return {f.id: f"{f.total}:{f.unread}" for f in await self.list_folders()}

    async def folder_contents(self, folder_id: str) -> list[str]:
        items = await self._all(
            f"/me/mailFolders/{_id(folder_id)}/messages",
            {"$select": "id", "$top": str(BATCH)},
        )
        return [str(item["id"]) for item in items]

    async def message_headers(self, message_ids: list[str]) -> dict[str, str | None]:
        found: dict[str, str | None] = {}
        for message_id in message_ids:
            try:
                item = await self._json(
                    "GET",
                    f"/me/messages/{_id(message_id)}",
                    params={"$select": "internetMessageId"},
                )
            except NotFoundError:
                continue
            found[message_id] = item.get("internetMessageId")
        return found

    async def wait_for_change(self, timeout: float) -> bool:
        """No push yet: Graph's change notifications need a public endpoint
        (CONCEPT 5.4)."""
        return False

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
    # A full link names the version; a cursor handed out before does not.
    rest = parts.path.removeprefix(VERSION) if parts.netloc else parts.path
    if not rest.startswith("/me/") or ".." in rest:
        raise BadRequestError("invalid cursor")
    return f"{rest}?{parts.query}" if parts.query else rest


def _with_bcc(raw: bytes, recipients: list[str]) -> bytes:
    """``raw`` with a Bcc header for the recipients no header names."""
    head, separator, body = raw.partition(b"\r\n\r\n")
    headers = BytesHeaderParser(policy=default).parsebytes(head + separator)
    named = {
        address.lower()
        for _, address in getaddresses(
            [str(v) for n in ("To", "Cc", "Bcc") for v in headers.get_all(n, [])]
        )
    }
    hidden = [r for r in recipients if r.lower() not in named]
    if not hidden:
        return raw
    return head + b"\r\nBcc: " + ", ".join(hidden).encode() + separator + body


def _failure(answer: Answer) -> MailboxApiError:
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
