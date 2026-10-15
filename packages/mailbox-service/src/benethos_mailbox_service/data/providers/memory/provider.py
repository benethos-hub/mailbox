"""An in-memory provider for tests and local development. No network.

It holds what the mailbox holds itself (``store``), where tests look at
it. The parts are in ``messages``, ``folders`` and ``drafts``, as the
adapters of real servers have them."""

from __future__ import annotations

from ....errors import MailboxServiceError
from ...mail import ThreadHeaders
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
from . import drafts, folders, messages, store


class MemoryProvider:
    stable_ids = True

    def __init__(
        self,
        folders: list[Folder] | None = None,
        messages: list[Message] | None = None,
        abilities: Abilities | None = None,
    ) -> None:
        """``abilities``: what the account answers it can do, by default
        what its folders allow."""
        self.given = abilities
        # Whether a message may sit in several folders.
        self.labels = False
        self.folders = folders or [
            Folder(id="inbox", name="Inbox", role=FolderRole.INBOX),
            Folder(id="sent", name="Sent", role=FolderRole.SENT),
            Folder(id="drafts", name="Drafts", role=FolderRole.DRAFTS),
        ]
        self.messages = messages or []
        self.attachment_data: dict[tuple[str, str], bytes] = {}
        # The source of every stored draft, by id.
        self.raws: dict[str, bytes] = {}
        self.drafts_saved = 0
        # (sender, recipients, raw) of every send, for tests.
        self.outbox: list[tuple[str, list[str], bytes]] = []

    # --- Reads ------------------------------------------------------------------------

    async def list_folders(self) -> list[Folder]:
        return list(self.folders)

    async def list_messages(
        self,
        folder_id: str,
        *,
        limit: int,
        cursor: str | None,
        search: MessageFilter | None = None,
    ) -> Page[MessageSummary]:
        return messages.list_messages(self, folder_id, limit, cursor, search)

    async def get_message(self, message_id: str) -> Message:
        return store.message(self, message_id)

    async def get_attachment(
        self, message_id: str, attachment_id: str
    ) -> AttachmentContent:
        return messages.get_attachment(self, message_id, attachment_id)

    async def get_raw(self, message_id: str) -> bytes:
        return messages.get_raw(self, message_id)

    async def folder_states(self) -> dict[str, str]:
        return {
            f.id: ",".join(m.id for m in self.messages if f.id in m.folder_ids)
            for f in self.folders
        }

    async def folder_contents(self, folder_id: str) -> list[str]:
        return [m.id for m in self.messages if folder_id in m.folder_ids]

    async def message_headers(self, message_ids: list[str]) -> dict[str, ThreadHeaders]:
        wanted = set(message_ids)
        return {
            m.id: ThreadHeaders(m.message_id_header)
            for m in self.messages
            if m.id in wanted
        }

    async def abilities(self) -> Abilities:
        if self.given is not None:
            return self.given
        roles = {folder.role for folder in self.folders}
        found = {
            Capability.READ_STATE,
            Capability.STARS,
            Capability.KEYWORDS,
            Capability.FOLDERS,
            Capability.MOVE,
            Capability.PURGE,
            Capability.SEARCH,
            Capability.SEND,
        }
        for role, capability in (
            (FolderRole.TRASH, Capability.TRASH),
            (FolderRole.DRAFTS, Capability.DRAFTS),
            (FolderRole.SENT, Capability.SENT_COPY),
        ):
            if role in roles:
                found.add(capability)
        if self.labels:
            found.add(Capability.LABELS)
        return Abilities.of(found, written=set(Mark))

    async def verify(self) -> None:
        return None

    async def close(self) -> None:
        return None

    # --- Writes -----------------------------------------------------------------------

    async def create_folder(self, name: str, parent_id: str | None) -> Folder:
        return folders.create_folder(self, name, parent_id)

    async def update_folder(
        self, folder_id: str, name: str, parent_id: str | None
    ) -> Folder:
        return folders.update_folder(self, folder_id, name, parent_id)

    async def delete_folder(self, folder_id: str) -> None:
        folders.delete_folder(self, folder_id)

    async def update_messages(
        self, message_ids: list[str], changes: MessageUpdate
    ) -> dict[str, MessageSummary | MailboxServiceError]:
        return await messages.update_messages(self, message_ids, changes)

    async def delete_messages(
        self, message_ids: list[str], permanent: bool
    ) -> dict[str, MessageSummary | None | MailboxServiceError]:
        return await messages.delete_messages(self, message_ids, permanent)

    # --- Sends, Drafts ----------------------------------------------------------------

    async def send(self, raw: bytes, sender: str, recipients: list[str]) -> SentMessage:
        """Records what was sent in ``outbox`` and keeps a copy in the sent
        folder."""
        return drafts.send(self, raw, sender, recipients)

    async def list_drafts(
        self, *, limit: int, cursor: str | None
    ) -> Page[MessageSummary]:
        return drafts.list_drafts(self, limit, cursor)

    async def save_draft(self, raw: bytes, replaces: str | None) -> MessageSummary:
        return drafts.save_draft(self, raw, replaces)

    async def get_draft(self, draft_id: str) -> bytes:
        return drafts.get_draft(self, draft_id)

    async def delete_draft(self, draft_id: str) -> None:
        drafts.delete_draft(self, draft_id)
