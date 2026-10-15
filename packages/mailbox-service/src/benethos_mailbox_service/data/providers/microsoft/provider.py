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

The wire, the well-known folders and Graph's errors are in ``api``, a
folder's messages in ``listing``, the parts in ``folders``, ``messages``,
``drafts`` and ``changes``. Exchange has no folder ``all``: the adapter
shows one, every folder but the trash and junk (UNIFORM 6.5).

Details Graph's documentation leaves open are marked **(unverified)**
until a live check against a Microsoft account confirms them. Seen live:
search results come under ids that change on a move, despite the
preference. The adapter looks their immutable ids up.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from datetime import datetime

import anyio

from ....errors import MailboxServiceError
from ...mail import ThreadHeaders, convert
from ...models import (
    Abilities,
    AttachmentContent,
    Capability,
    Folder,
    Mark,
    Message,
    MessageFilter,
    MessageSummary,
    MessageUpdate,
    Page,
    SentMessage,
)
from ...protocols import ApiClient
from ..base import FolderChanges, ThreadMessages, TokenSource
from . import changes, drafts, folders, listing, messages
from .api import Graph

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

    # --- Reads ------------------------------------------------------------------------

    async def list_folders(self) -> list[Folder]:
        return await folders.list_folders(self._graph)

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
        return await messages.get_message(self._graph, message_id)

    async def get_attachment(
        self, message_id: str, attachment_id: str
    ) -> AttachmentContent:
        return convert.attachment_of(await self.get_raw(message_id), attachment_id)

    async def get_raw(self, message_id: str) -> bytes:
        return await messages.get_raw(self._graph, message_id)

    async def thread_messages(self, thread_id: str, limit: int) -> ThreadMessages:
        return await messages.thread_messages(self._graph, thread_id, limit)

    async def folder_states(self) -> dict[str, str]:
        return await changes.folder_states(self._graph)

    async def folder_contents(self, folder_id: str) -> list[str]:
        return await changes.folder_contents(self._graph, folder_id)

    async def message_headers(self, message_ids: list[str]) -> dict[str, ThreadHeaders]:
        return await changes.message_headers(self._graph, message_ids)

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

    # --- Writes -----------------------------------------------------------------------

    async def create_folder(self, name: str, parent_id: str | None) -> Folder:
        return await folders.create_folder(self._graph, name, parent_id)

    async def update_folder(
        self, folder_id: str, name: str, parent_id: str | None
    ) -> Folder:
        return await folders.update_folder(self._graph, folder_id, name, parent_id)

    async def delete_folder(self, folder_id: str) -> None:
        await folders.delete_folder(self._graph, folder_id)

    async def update_messages(
        self, message_ids: list[str], changes: MessageUpdate
    ) -> dict[str, MessageSummary | MailboxServiceError]:
        return await messages.update_messages(self._graph, message_ids, changes)

    async def delete_messages(
        self, message_ids: list[str], permanent: bool
    ) -> dict[str, MessageSummary | None | MailboxServiceError]:
        return await messages.delete_messages(self._graph, message_ids, permanent)

    # --- Sends, Drafts ----------------------------------------------------------------

    async def send(self, raw: bytes, sender: str, recipients: list[str]) -> SentMessage:
        return await drafts.send(self._graph, raw, recipients)

    async def list_drafts(
        self, *, limit: int, cursor: str | None
    ) -> Page[MessageSummary]:
        return await drafts.list_drafts(self._graph, limit, cursor)

    async def save_draft(self, raw: bytes, replaces: str | None) -> MessageSummary:
        return await drafts.save_draft(self._graph, raw, replaces)

    async def get_draft(self, draft_id: str) -> bytes:
        return await drafts.get_draft(self._graph, draft_id)

    async def delete_draft(self, draft_id: str) -> None:
        await drafts.delete_draft(self._graph, draft_id)

    # --- Deltas -----------------------------------------------------------------------

    async def folder_changes(
        self, folder_id: str, token: str | None, since: datetime | None = None
    ) -> FolderChanges:
        """Every message carries when it came, so ``since`` asks nothing
        more."""
        return await changes.folder_changes(self._graph, folder_id, token)
