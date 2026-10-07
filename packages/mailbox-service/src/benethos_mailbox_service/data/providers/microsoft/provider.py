"""Microsoft 365 and Outlook.com over Microsoft Graph (CONCEPT 5.4).

Every call carries the account's access token from its ``TokenSource`` and
asks for immutable ids, so a message keeps its id when it moves
(``STABLE_IDS``). A refused token is renewed once. If it is refused
again, the account needs a new sign-in.

Sending and drafts go as MIME, composed by ``data.mail.compose`` like for
any other provider: ``sendMail`` sends and keeps the copy in Sent Items, a
draft is created from MIME and replaced by creating a new one. Graph cannot
change a draft's MIME in place.

The wire, the well-known folders and Graph's errors are in ``graph``.

Details Graph's documentation leaves open are marked **(unverified)**
until a live check against a Microsoft account confirms them. Seen live:
search results come under ids that change on a move, despite the
preference. The adapter looks their immutable ids up.
"""

from __future__ import annotations

import base64
import time
from collections.abc import Callable
from urllib.parse import unquote, urlencode

from ....errors import (
    BadRequestError,
    ConflictError,
    MailboxServiceError,
    ProviderError,
    missing,
)
from ...mail import compose, convert, parse
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
from ...protocols import ApiClient
from .. import rules
from ..base import Capability, ChangedMessage, FolderChanges, TokenSource
from . import mappers
from .graph import Graph, id_, own_path
from .shapes import Attachment, Batch, Item, Listing, MailFolder
from .shapes import Message as GraphMessage

# A page of folders or of message ids, as many as Graph hands out at once.
PAGE_SIZE = 250


class MicrosoftProvider:
    capabilities = frozenset(
        {
            Capability.SEND,
            Capability.SEARCH,
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
        self._graph = Graph(tokens, http, clock)

    # --- folders --------------------------------------------------------------------

    async def list_folders(self) -> list[Folder]:
        roles = await self._graph.folder_roles()
        root = await self._graph.root_id()
        params = {"$select": mappers.FOLDER_FIELDS, "$top": str(PAGE_SIZE)}
        found: list[Folder] = []
        waiting = await self._graph.all(Listing[MailFolder], "/me/mailFolders", params)
        while waiting:
            item = waiting.pop(0)
            found.append(mappers.folder(item, roles, root))
            if item.child_folder_count:
                waiting.extend(
                    await self._graph.all(
                        Listing[MailFolder],
                        f"/me/mailFolders/{id_(item.id)}/childFolders",
                        params,
                    )
                )
        return found

    async def create_folder(self, name: str, parent_id: str | None) -> Folder:
        path = (
            f"/me/mailFolders/{id_(parent_id)}/childFolders"
            if parent_id
            else "/me/mailFolders"
        )
        item = await self._graph.read(
            MailFolder, "POST", path, json_body={"displayName": name}
        )
        return mappers.folder(
            item, await self._graph.folder_roles(), await self._graph.root_id()
        )

    async def update_folder(
        self, folder_id: str, name: str, parent_id: str | None
    ) -> Folder:
        path = f"/me/mailFolders/{id_(folder_id)}"
        item = await self._graph.read(
            MailFolder, "PATCH", path, json_body={"displayName": name}
        )
        # The top of the folder tree is the mailbox's root folder, which
        # Graph names as the parent of a top-level folder.
        root = await self._graph.root_id()
        if (item.parent_folder_id or root) != (parent_id or root):
            item = await self._graph.move(MailFolder, path, parent_id or root)
        return mappers.folder(item, await self._graph.folder_roles(), root)

    async def delete_folder(self, folder_id: str) -> None:
        await self._graph.call("DELETE", f"/me/mailFolders/{id_(folder_id)}")

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
            body = await self._graph.read(
                Listing[GraphMessage], "GET", own_path(cursor)
            )
        else:
            path = (
                f"/me/mailFolders/{id_(folder_id)}/messages"
                if folder_id
                else "/me/messages"
            )
            params = {"$select": mappers.SUMMARY_FIELDS, "$top": str(limit), **query}
            body = await self._graph.read(
                Listing[GraphMessage], "GET", path, params=params
            )
        found = body.value
        if "$search" in query or (cursor and "search=" in unquote(cursor)):
            found = await self._immutable(found)
        items = [mappers.summary(item) for item in found]
        link = body.next_link
        return Page[MessageSummary](
            items=[item for item in items if mappers.keeps(item, rest)],
            next_cursor=own_path(link) if link else None,
        )

    async def _immutable(self, items: list[GraphMessage]) -> list[GraphMessage]:
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
        wanted = [item for item in items if item.internet_message_id]
        urls = []
        for item in wanted:
            header = (item.internet_message_id or "").replace("'", "''")
            query = urlencode(
                {
                    "$select": "id,parentFolderId",
                    "$filter": f"internetMessageId eq '{header}'",
                }
            )
            urls.append(f"/me/messages?{query}")
        found = await self._graph.batch(urls, Batch[Listing[GraphMessage]])
        for n, body in found.items():
            item = wanted[n]
            same = [
                f for f in body.value if f.parent_folder_id == item.parent_folder_id
            ]
            if len(same) == 1:
                ids[item.id] = same[0].id
        return [
            item.model_copy(update={"id": ids.get(item.id, item.id)}) for item in items
        ]

    async def get_message(self, message_id: str) -> Message:
        path = f"/me/messages/{id_(message_id)}"
        item = await self._graph.read(
            GraphMessage, "GET", path, params={"$select": mappers.MESSAGE_FIELDS}
        )
        attachments: list[Attachment] = []
        if item.has_attachments:
            attachments = await self._graph.all(
                Listing[Attachment],
                f"{path}/attachments",
                {"$select": "id,name,contentType,size,isInline"},
            )
        found = mappers.message(item, attachments)
        if item.is_draft:
            # What a draft answers lives in its MIME only.
            thread = convert.thread_fields(
                parse.ParsedMessage(await self.get_raw(message_id))
            )
            found = found.model_copy(
                update={k: thread[k] for k in ("reference", "in_reply_to")}
            )
        return found

    async def get_attachment(
        self, message_id: str, attachment_id: str
    ) -> AttachmentContent:
        path = f"/me/messages/{id_(message_id)}/attachments/{id_(attachment_id)}"
        item = await self._graph.read(Attachment, "GET", path)
        content = item.content_bytes
        data = (
            base64.b64decode(content)
            if content
            else (await self._graph.call("GET", f"{path}/$value")).body
        )
        return mappers.attachment_content(item, data)

    async def get_raw(self, message_id: str) -> bytes:
        return (
            await self._graph.call("GET", f"/me/messages/{id_(message_id)}/$value")
        ).body

    async def send(self, raw: bytes, sender: str, recipients: list[str]) -> SentMessage:
        """Graph takes the recipients from the MIME headers, and keeps the
        copy in Sent Items itself. Recipients the headers do not name are
        the Bcc ones: they go in a Bcc header, which Exchange takes out
        before delivery **(unverified)**."""
        await self._graph.call(
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
        drafts = await self._graph.role_id(FolderRole.DRAFTS)
        return await self.list_messages(drafts, limit=limit, cursor=cursor)

    async def save_draft(self, raw: bytes, replaces: str | None) -> MessageSummary:
        if replaces is not None:
            await self._draft(replaces)
        item = await self._graph.read(
            GraphMessage,
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
            draft = (await self._graph.placed(f"/me/messages/{id_(draft_id)}")).is_draft
        except BadRequestError:
            draft = False
        if not draft:
            raise missing("draft", draft_id)

    # --- changing -------------------------------------------------------------------

    async def update_messages(
        self, message_ids: list[str], changes: MessageUpdate
    ) -> dict[str, MessageSummary | MailboxServiceError]:
        body = mappers.changes(changes.unread, changes.starred, changes.keywords)

        async def one(message_id: str) -> MessageSummary:
            # Judged per id, as the other adapters answer it.
            target = rules.move_target(changes, self.capabilities)
            path = f"/me/messages/{id_(message_id)}"
            item = None
            if body:
                item = await self._graph.read(
                    GraphMessage, "PATCH", path, json_body=body
                )
            if target is not None:
                item = await self._graph.move(GraphMessage, path, target)
            if item is None:
                item = await self._graph.read(
                    GraphMessage,
                    "GET",
                    path,
                    params={"$select": mappers.SUMMARY_FIELDS},
                )
            return mappers.summary(item)

        return await rules.per_id(message_ids, one)

    async def delete_messages(
        self, message_ids: list[str], permanent: bool
    ) -> dict[str, MessageSummary | None | MailboxServiceError]:
        try:
            trash = await self._graph.role_id(FolderRole.TRASH)
        except ConflictError as exc:
            return dict.fromkeys(message_ids, exc)

        async def one(message_id: str) -> MessageSummary | None:
            if permanent:
                await self._delete_for_good(message_id, trash)
                return None
            path = f"/me/messages/{id_(message_id)}"
            if (await self._graph.placed(path)).parent_folder_id == trash:
                raise rules.in_trash_already()
            return mappers.summary(await self._graph.move(GraphMessage, path, trash))

        return await rules.per_id(message_ids, one)

    async def _delete_for_good(self, message_id: str, trash: str | None = None) -> None:
        """Graph's DELETE outside the trash only moves the message there.
        For good means: into the trash, then deleted from it."""
        if trash is None:
            trash = await self._graph.role_id(FolderRole.TRASH)
        path = f"/me/messages/{id_(message_id)}"
        if (await self._graph.placed(path)).parent_folder_id != trash:
            item = await self._graph.move(Item, path, trash)
            path = f"/me/messages/{id_(item.id)}"
        await self._graph.call("DELETE", path)

    # --- for the sync worker ------------------------------------------------------
    # Ids are stable: the domain keeps no id mapping for this provider, so
    # these serve checks such as "is the folder empty".

    async def folder_states(self) -> dict[str, str]:
        """Graph reports no UIDNEXT: the counts stand in. A message that
        arrives read while another leaves goes unnoticed until the next
        change, which the sync then catches up on."""
        return {f.id: f"{f.total}:{f.unread}" for f in await self.list_folders()}

    async def folder_contents(self, folder_id: str) -> list[str]:
        items = await self._graph.all(
            Listing[Item],
            f"/me/mailFolders/{id_(folder_id)}/messages",
            {"$select": "id", "$top": str(PAGE_SIZE)},
        )
        return [item.id for item in items]

    async def flag_changes(
        self, folder_id: str, since: str, message_ids: list[str]
    ) -> list[str]:
        """Graph reports changes through delta queries instead."""
        return []

    async def message_headers(self, message_ids: list[str]) -> dict[str, str | None]:
        """Twenty to a JSON batch. A message that is gone is left out."""
        urls = [
            f"/me/messages/{id_(message_id)}?$select=internetMessageId"
            for message_id in message_ids
        ]
        found = await self._graph.batch(urls, Batch[GraphMessage])
        return {message_ids[n]: body.internet_message_id for n, body in found.items()}

    async def folder_changes(self, folder_id: str, token: str | None) -> FolderChanges:
        """A delta query of the folder's messages. The token is Graph's
        deltaLink, below ``/v1.0``. A message moved out of the folder comes
        as removed, one moved in as changed, under the same immutable id."""
        if token is None:
            body = await self._graph.read(
                Listing[GraphMessage],
                "GET",
                f"/me/mailFolders/{id_(folder_id)}/messages/delta",
                params={"$select": "id,createdDateTime"},
            )
        else:
            body = await self._graph.read(Listing[GraphMessage], "GET", own_path(token))
        changed: list[ChangedMessage] = []
        removed: list[str] = []
        delta = None
        async for page in self._graph.pages(body):
            for item in page.value:
                if item.removed is not None:
                    removed.append(item.id)
                else:
                    changed.append(ChangedMessage(item.id, item.created_date_time))
            delta = page.delta_link
        if not delta:
            raise ProviderError("microsoft answered a delta query without a link")
        return FolderChanges(own_path(delta), changed, removed)

    async def verify(self) -> None:
        self._graph.forget()
        self._graph.tokens.forget_refusal()
        await self._graph.call("GET", "/me/mailFolders/inbox", params={"$select": "id"})

    async def close(self) -> None:
        await self._graph.close()
