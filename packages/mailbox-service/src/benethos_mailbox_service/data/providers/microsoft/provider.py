"""Microsoft 365 and Outlook.com over Microsoft Graph (CONCEPT 5.4).

Every call carries the account's access token from its ``TokenSource`` and
asks for immutable ids, so a message keeps its id when it moves
(``STABLE_IDS``). A refused token is renewed once. If it is refused
again, the account needs a new sign-in.

Each message names its conversation, which Graph lists across the
folders (``THREADS``).

Sending and drafts go as MIME, composed by ``data.mail.compose`` like for
any other provider: a draft is created from MIME and replaced by creating
a new one, since Graph cannot change a draft's MIME in place. A mail is
sent as such a draft, whose id its copy in Sent Items keeps. A draft
too large for one request gets its files one by one (``uploads``). A message
is read from its MIME too, so its bodies, headers and attachments are
what the other providers answer.

The wire, the well-known folders and Graph's errors are in ``graph``, a
folder's messages in ``listing``. Exchange has no folder ``all``: the
adapter shows one, every folder but the trash and junk (UNIFORM 6.5).

Details Graph's documentation leaves open are marked **(unverified)**
until a live check against a Microsoft account confirms them. Seen live:
search results come under ids that change on a move, despite the
preference. The adapter looks their immutable ids up.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

import anyio

from ....errors import (
    BadRequestError,
    ConflictError,
    MailboxServiceError,
    ProviderError,
    missing,
)
from ...mail import ThreadHeaders, compose, convert, parse
from ...models import (
    Abilities,
    AttachmentContent,
    Capability,
    Folder,
    FolderRole,
    Mark,
    Message,
    MessageFilter,
    MessageSummary,
    MessageUpdate,
    Page,
    SentMessage,
)
from ...protocols import ApiClient
from .. import rules
from ..base import (
    ChangedMessage,
    FolderChanges,
    ThreadMessages,
    TokenSource,
)
from . import listing, mappers, uploads
from .graph import Graph, id_, own_path
from .shapes import Batch, Item, Listing, MailFolder
from .shapes import Message as GraphMessage

# A page of folders or of message ids, as many as Graph hands out at once.
PAGE_SIZE = 250


ABILITIES = Abilities.of(
    {
        Capability.READ_STATE,
        Capability.STARS,
        Capability.KEYWORDS,
        Capability.FOLDERS,
        Capability.MOVE,
        Capability.TRASH,
        Capability.PURGE,
        Capability.SEARCH,
        Capability.DRAFTS,
        Capability.SEND,
        Capability.SENT_COPY,
        Capability.THREADS,
        Capability.EXTERNAL_CHANGES,
    },
    read={Mark.DRAFT},
    written={Mark.ANSWERED, Mark.FORWARDED},
)


class MicrosoftProvider:
    stable_ids = True

    def __init__(
        self,
        tokens: TokenSource,
        http: ApiClient | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = anyio.sleep,
    ) -> None:
        self._graph = Graph(tokens, http, clock, sleep)

    # --- folders --------------------------------------------------------------------

    async def list_folders(self) -> list[Folder]:
        return [*await self._folders(), mappers.all_mail()]

    async def _folders(self) -> list[Folder]:
        """The folders Exchange keeps, without ``all``."""
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
        folder_id: str,
        *,
        limit: int,
        cursor: str | None,
        search: MessageFilter | None = None,
    ) -> Page[MessageSummary]:
        return await listing.list_messages(
            self._graph, folder_id, limit, cursor, search
        )

    async def get_message(self, message_id: str) -> Message:
        """What Graph knows of the message, and what its MIME says: the
        bodies, the headers and the attachments as the mail has them, read
        as for any other provider. Graph's own fields would answer
        Exchange's HTML for a plain text mail, and no attachments for a mail
        with inline images only."""
        item = await self._summary_of(f"/me/messages/{id_(message_id)}")
        return mappers.message(item, await self.get_raw(message_id))

    async def get_attachment(
        self, message_id: str, attachment_id: str
    ) -> AttachmentContent:
        parsed = parse.ParsedMessage(await self.get_raw(message_id))
        return convert.attachment(parsed, attachment_id)

    async def get_raw(self, message_id: str) -> bytes:
        return (
            await self._graph.call("GET", f"/me/messages/{id_(message_id)}/$value")
        ).body

    async def send(self, raw: bytes, sender: str, recipients: list[str]) -> SentMessage:
        """The way Microsoft documents to learn the sent copy: the MIME is
        saved as a draft, which is sent. The copy in Sent Items keeps the
        draft's immutable id. Graph takes the recipients from the MIME
        headers. Recipients the headers do not name are the Bcc ones: they
        go in a Bcc header, which Exchange takes out before delivery
        **(unverified)**. A draft that cannot be sent is deleted again."""
        draft = await uploads.create_draft(
            self._graph, compose.with_bcc(raw, recipients), self._delete_for_good
        )
        try:
            await self._graph.call("POST", f"/me/messages/{id_(draft.id)}/send")
        except MailboxServiceError as exc:
            try:
                await self._delete_for_good(draft.id)
            except MailboxServiceError:
                raise exc.noting(f"it stays as the draft {draft.id}") from None
            raise
        roles = await self._graph.folder_roles()
        sent = next((k for k, v in roles.items() if v is FolderRole.SENT), None)
        return SentMessage(sent_copy=mappers.sent_copy(draft, sent))

    # --- drafts ---------------------------------------------------------------------

    async def list_drafts(
        self, *, limit: int, cursor: str | None
    ) -> Page[MessageSummary]:
        drafts = await self._graph.role_id(FolderRole.DRAFTS)
        return await self.list_messages(drafts, limit=limit, cursor=cursor)

    async def save_draft(self, raw: bytes, replaces: str | None) -> MessageSummary:
        if replaces is not None:
            await self._draft(replaces)
        item = await uploads.create_draft(self._graph, raw, self._delete_for_good)
        if replaces is not None:
            await rules.replaced(
                item.id,
                lambda: self._delete_for_good(replaces),
                lambda: self._delete_for_good(item.id),
            )
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
            target = rules.move_target(changes, labels=False)
            if target == mappers.ALL:
                raise rules.into_all()
            path = f"/me/messages/{id_(message_id)}"
            item = None
            verb: dict[str, Any] = {}
            if mappers.touches_marks(changes):
                # Refused before anything changes.
                item = await self._summary_of(path)
                verb = mappers.verb_after(item, changes)
            if changes.add_keywords or changes.remove_keywords:
                item = item or await self._summary_of(path)
                categories = mappers.categories_after(item, changes)
                patch = {**body, **mappers.changes(None, None, categories), **verb}
            else:
                patch = {**body, **verb}
            if patch:
                await self._graph.call("PATCH", path, json_body=patch)
            if target is not None:
                await self._graph.move(GraphMessage, path, target)
            # Read again: Graph answers a change without the verb that says
            # whether the message is answered. Its id survives the move.
            return mappers.summary(await self._summary_of(path))

        return await rules.per_id(message_ids, one)

    async def _summary_of(self, path: str) -> GraphMessage:
        return await self._graph.read(
            GraphMessage, "GET", path, params=mappers.SUMMARY_PARAMS
        )

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
        moved = None
        if (await self._graph.placed(path)).parent_folder_id != trash:
            moved = await self._graph.move(Item, path, trash)
            path = f"/me/messages/{id_(moved.id)}"
        try:
            await self._graph.call("DELETE", path)
        except MailboxServiceError as exc:
            if moved is None:
                raise
            raise exc.noting("the message is in the trash now") from None

    # --- for the sync worker ------------------------------------------------------
    # Ids are stable: the domain keeps no id mapping for this provider, so
    # these serve checks such as "is the folder empty".

    async def folder_states(self) -> dict[str, str]:
        """Graph reports no UIDNEXT: the counts stand in. A message that
        arrives read while another leaves goes unnoticed until the next
        change, which the sync then catches up on."""
        return {f.id: f"{f.total}:{f.unread}" for f in await self._folders()}

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

    async def thread_messages(self, thread_id: str, limit: int) -> ThreadMessages:
        """A conversation's messages in every folder, filtered by its id,
        seen live. Graph refuses an order beside this filter, so they are
        sorted here. Of a longer conversation the pages read first are kept
        **(unverified)**."""
        conversation = thread_id.replace("'", "''")
        params = {
            **mappers.SUMMARY_PARAMS,
            "$filter": f"conversationId eq '{conversation}'",
            "$top": str(PAGE_SIZE),
        }
        body = await self._graph.read(
            Listing[GraphMessage], "GET", "/me/messages", params=params
        )
        found = list(body.value)
        link = body.next_link
        while link and len(found) <= limit:
            body = await self._graph.read(Listing[GraphMessage], "GET", own_path(link))
            found += body.value
            link = body.next_link
        if not found:
            raise missing("thread", thread_id)
        every = sorted(
            (mappers.summary(item) for item in found),
            key=lambda m: (m.received is None, m.received),
        )
        return ThreadMessages(
            every[-limit:], truncated=bool(link) or len(every) > limit
        )

    async def message_headers(self, message_ids: list[str]) -> dict[str, ThreadHeaders]:
        """Twenty to a JSON batch. A message that is gone is left out."""
        urls = [
            f"/me/messages/{id_(message_id)}?$select=internetMessageId"
            for message_id in message_ids
        ]
        found = await self._graph.batch(urls, Batch[GraphMessage])
        return {
            message_ids[n]: ThreadHeaders(body.internet_message_id)
            for n, body in found.items()
        }

    async def folder_changes(
        self, folder_id: str, token: str | None, since: datetime | None = None
    ) -> FolderChanges:
        """A delta query of the folder's messages. The token is Graph's
        deltaLink, below ``/v1.0``. A message moved out of the folder comes
        as removed, one moved in as changed, under the same immutable id.
        Every message carries when it came, so ``since`` asks nothing more."""
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

    async def abilities(self) -> Abilities:
        """The same for every Microsoft account. Its keywords are Outlook's
        categories. It reads ``$draft``, and reads and writes ``$answered``
        and ``$forwarded`` as the verb Outlook last carried out (``marks``,
        UNIFORM 6.4)."""
        return ABILITIES

    async def verify(self) -> None:
        self._graph.forget()
        self._graph.tokens.forget_refusal()
        await self._graph.call("GET", "/me/mailFolders/inbox", params={"$select": "id"})

    async def close(self) -> None:
        await self._graph.close()
