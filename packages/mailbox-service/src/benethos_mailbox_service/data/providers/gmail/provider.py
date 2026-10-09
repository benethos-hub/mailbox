"""Gmail and Google Workspace over the Gmail API (CONCEPT 5.3, 5.5).

JSON over HTTPS, no Google SDK. Every call carries the account's access
token from its ``TokenSource``. A refused token is renewed once. If it is
refused again, the account needs a new sign-in.

Ids are Gmail's own and stay when a message moves (``STABLE_IDS``).
Labels are folders, so a message can be in several (``LABELS``). The
sync asks what changed since a history id (``DELTA``). There is no
push: Gmail pushes through Cloud Pub/Sub only, which needs more of
Google Cloud set up. The worker asks instead.

The parts are in ``api`` (the wire), ``messages``, ``folders``,
``sending`` (with the drafts) and ``changes``. ``live/gmail.py`` checks
them against a Gmail account.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime

from ....common.clock import utc_now
from ....errors import MailboxServiceError
from ...models import (
    AttachmentContent,
    Folder,
    Message,
    MessageFilter,
    MessageSummary,
    MessageUpdate,
    Page,
    SentMessage,
)
from ...protocols import ApiClient
from ..base import Capability, FolderChanges, TokenSource
from . import folders, messages, sending
from .api import GmailApi
from .changes import Changes
from .shapes import Profile


class GmailProvider:
    capabilities = frozenset(
        {
            Capability.SEND,
            Capability.SEARCH,
            Capability.SERVER_SEARCH,
            Capability.LABELS,
            Capability.STABLE_IDS,
        }
    )

    def __init__(
        self,
        tokens: TokenSource,
        http: ApiClient | None = None,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = utc_now,
    ) -> None:
        self._api = GmailApi(tokens, http, clock)
        self._changes = Changes(self._api, now)

    # --- Reads ------------------------------------------------------------------------

    async def list_folders(self) -> list[Folder]:
        return await folders.list_folders(self._api)

    async def list_messages(
        self,
        folder_id: str | None,
        *,
        limit: int,
        cursor: str | None,
        search: MessageFilter | None = None,
    ) -> Page[MessageSummary]:
        return await messages.list_messages(self._api, folder_id, limit, cursor, search)

    async def get_message(self, message_id: str) -> Message:
        return await messages.get_message(self._api, message_id)

    async def get_attachment(
        self, message_id: str, attachment_id: str
    ) -> AttachmentContent:
        return await messages.get_attachment(self._api, message_id, attachment_id)

    async def get_raw(self, message_id: str) -> bytes:
        return await messages.get_raw(self._api, message_id)

    async def folder_states(self) -> dict[str, str]:
        return await self._changes.folder_states()

    async def folder_contents(self, folder_id: str) -> list[str]:
        return await self._changes.folder_contents(folder_id)

    async def message_headers(self, message_ids: list[str]) -> dict[str, str | None]:
        return await self._changes.message_headers(message_ids)

    async def flag_changes(
        self, folder_id: str, since: str, message_ids: list[str]
    ) -> list[str]:
        """Gmail reports changes since a history id instead."""
        return []

    async def verify(self) -> None:
        self._api.forget()
        self._api.tokens.forget_refusal()
        await self._api.read(Profile, "GET", "/profile")

    async def close(self) -> None:
        await self._api.close()

    # --- Writes -----------------------------------------------------------------------

    async def create_folder(self, name: str, parent_id: str | None) -> Folder:
        return await folders.create_folder(self._api, name, parent_id)

    async def update_folder(
        self, folder_id: str, name: str, parent_id: str | None
    ) -> Folder:
        return await folders.update_folder(self._api, folder_id, name, parent_id)

    async def delete_folder(self, folder_id: str) -> None:
        await folders.delete_folder(self._api, folder_id)

    async def update_messages(
        self, message_ids: list[str], changes: MessageUpdate
    ) -> dict[str, MessageSummary | MailboxServiceError]:
        return await messages.update_messages(
            self._api, self.capabilities, message_ids, changes
        )

    async def delete_messages(
        self, message_ids: list[str], permanent: bool
    ) -> dict[str, MessageSummary | None | MailboxServiceError]:
        return await messages.delete_messages(self._api, message_ids, permanent)

    # --- Sends, Drafts ----------------------------------------------------------------

    async def send(self, raw: bytes, sender: str, recipients: list[str]) -> SentMessage:
        return await sending.send(self._api, raw, sender, recipients)

    async def list_drafts(
        self, *, limit: int, cursor: str | None
    ) -> Page[MessageSummary]:
        return await sending.list_drafts(self._api, limit, cursor)

    async def save_draft(self, raw: bytes, replaces: str | None) -> MessageSummary:
        return await sending.save_draft(self._api, raw, replaces)

    async def get_draft(self, draft_id: str) -> bytes:
        return await sending.get_draft(self._api, draft_id)

    async def delete_draft(self, draft_id: str) -> None:
        await sending.delete_draft(self._api, draft_id)

    # --- Deltas -----------------------------------------------------------------------

    async def folder_changes(self, folder_id: str, token: str | None) -> FolderChanges:
        return await self._changes.folder_changes(folder_id, token)
