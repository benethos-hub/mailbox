"""JMAP servers (RFC 8620, 8621): Fastmail, Stalwart, Cyrus (CONCEPT 5.6).

JSON over HTTPS. Ids are the server's own and stay when a message moves
(``STABLE_IDS``), and a message can be in several folders (``LABELS``).
The sync asks what changed since a state (``DELTA``), and the server's
event source tells when something did (``PUSH``).

The account signs in with a password (HTTP Basic, e.g. Stalwart or Cyrus)
or an API token (Bearer, e.g. Fastmail). The credential is decrypted for
each request and not kept. The parts are in ``account`` (the wire),
``messages``, ``folders``, ``drafts``, ``sending`` and ``changes``.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime

from ....common.clock import utc_now
from ....errors import MailboxServiceError, ProviderError
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
from ...protocols import Pick, ServerClient, jmap
from ..base import Capability, CredentialReader, FolderChanges, ProviderSettings
from . import drafts, folders, messages, sending
from .account import JmapAccount
from .changes import Changes
from .connect import read_settings


class JmapProvider:
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
        found = read_settings(settings)
        server = jmap.JmapServer(
            host=found.host, port=found.port, path=found.path, pick=pick
        )
        self._account = JmapAccount(
            jmap.JmapClient(
                server,
                lambda: self._account.authorization(),
                http=http or ServerClient(pick=pick),
                clock=clock,
            ),
            credentials,
            found.auth,
            found.username,
        )
        self._changes = Changes(self._account, now)

    # --- Reads ------------------------------------------------------------------------

    async def list_folders(self) -> list[Folder]:
        return await self._account.folders()

    async def list_messages(
        self,
        folder_id: str | None,
        *,
        limit: int,
        cursor: str | None,
        search: MessageFilter | None = None,
    ) -> Page[MessageSummary]:
        return await messages.list_messages(
            self._account, folder_id, limit, cursor, search
        )

    async def get_message(self, message_id: str) -> Message:
        return await messages.get_message(self._account, message_id)

    async def get_attachment(
        self, message_id: str, attachment_id: str
    ) -> AttachmentContent:
        return await messages.get_attachment(self._account, message_id, attachment_id)

    async def get_raw(self, message_id: str) -> bytes:
        return await messages.get_raw(self._account, message_id)

    async def folder_states(self) -> dict[str, str]:
        return await self._changes.folder_states()

    async def folder_contents(self, folder_id: str) -> list[str]:
        return await self._changes.folder_contents(folder_id)

    async def message_headers(self, message_ids: list[str]) -> dict[str, str | None]:
        return await self._changes.message_headers(message_ids)

    async def flag_changes(
        self, folder_id: str, since: str, message_ids: list[str]
    ) -> list[str]:
        """JMAP reports changes since a state instead."""
        return []

    async def verify(self) -> None:
        """A fresh session, then one call: both need the credential."""
        session = await self._account.client.session(fresh=True)
        self._changes.forget()
        await self._account.one(
            "Mailbox/get", {"ids": [], "properties": ["id"]}, jmap.Anything
        )
        if not session.offers(jmap.MAIL):
            raise ProviderError("the server offers no JMAP mail for this login")

    async def close(self) -> None:
        await self._account.client.close()

    # --- Writes -----------------------------------------------------------------------

    async def create_folder(self, name: str, parent_id: str | None) -> Folder:
        return await folders.create_folder(self._account, name, parent_id)

    async def update_folder(
        self, folder_id: str, name: str, parent_id: str | None
    ) -> Folder:
        return await folders.update_folder(self._account, folder_id, name, parent_id)

    async def delete_folder(self, folder_id: str) -> None:
        await folders.delete_folder(self._account, folder_id)

    async def update_messages(
        self, message_ids: list[str], changes: MessageUpdate
    ) -> dict[str, MessageSummary | MailboxServiceError]:
        return await messages.update_messages(
            self._account, self.capabilities, message_ids, changes
        )

    async def delete_messages(
        self, message_ids: list[str], permanent: bool
    ) -> dict[str, MessageSummary | None | MailboxServiceError]:
        return await messages.delete_messages(self._account, message_ids, permanent)

    # --- Sends, Drafts ----------------------------------------------------------------

    async def send(self, raw: bytes, sender: str, recipients: list[str]) -> SentMessage:
        return await sending.send(self._account, raw, sender, recipients)

    async def list_drafts(
        self, *, limit: int, cursor: str | None
    ) -> Page[MessageSummary]:
        return await drafts.list_drafts(self._account, limit, cursor)

    async def save_draft(self, raw: bytes, replaces: str | None) -> MessageSummary:
        return await drafts.save_draft(self._account, raw, replaces)

    async def get_draft(self, draft_id: str) -> bytes:
        return await drafts.get_draft(self._account, draft_id)

    async def delete_draft(self, draft_id: str) -> None:
        await drafts.delete_draft(self._account, draft_id)

    # --- Watches, Deltas --------------------------------------------------------------

    async def wait_for_change(self, timeout: float) -> bool:
        return await self._changes.wait_for_change(timeout)

    async def folder_changes(self, folder_id: str, token: str | None) -> FolderChanges:
        return await self._changes.folder_changes(folder_id, token)
