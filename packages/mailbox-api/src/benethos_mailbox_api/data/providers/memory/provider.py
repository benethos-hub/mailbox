"""An in-memory provider for tests and local development. No network."""

from __future__ import annotations

from email.parser import BytesHeaderParser

from ....errors import (
    ConflictError,
    MailboxApiError,
    NotFoundError,
    NotSupportedError,
)
from ...models import (
    AttachmentContent,
    Folder,
    FolderRole,
    Message,
    MessageSummary,
    MessageUpdate,
    Page,
    SentMessage,
)
from ..base import Capability


class MemoryProvider:
    capabilities = frozenset(
        {Capability.SEND, Capability.DRAFTS, Capability.STABLE_IDS}
    )

    def __init__(
        self,
        folders: list[Folder] | None = None,
        messages: list[Message] | None = None,
    ) -> None:
        self.folders = folders or [
            Folder(id="inbox", name="Inbox", role=FolderRole.INBOX),
            Folder(id="sent", name="Sent", role=FolderRole.SENT),
        ]
        self.messages = messages or []
        self.attachment_data: dict[tuple[str, str], bytes] = {}
        # (sender, recipients, raw) of every send, for tests.
        self.outbox: list[tuple[str, list[str], bytes]] = []

    async def list_folders(self) -> list[Folder]:
        return list(self.folders)

    async def list_messages(
        self,
        folder_id: str | None,
        *,
        limit: int,
        cursor: str | None,
        query: str | None,
        unread: bool | None,
    ) -> Page[MessageSummary]:
        found = [
            m
            for m in self.messages
            if (folder_id is None or folder_id in m.folder_ids)
            and (unread is None or m.unread == unread)
            and (query is None or query.lower() in (m.subject or "").lower())
        ]
        start = int(cursor) if cursor else 0
        chunk = found[start : start + limit]
        more = start + limit < len(found)
        return Page[MessageSummary](
            items=[MessageSummary.model_validate(m.model_dump()) for m in chunk],
            next_cursor=str(start + limit) if more else None,
        )

    async def get_message(self, message_id: str) -> Message:
        for message in self.messages:
            if message.id == message_id:
                return message
        raise NotFoundError(f"message {message_id} not found")

    async def get_attachment(
        self, message_id: str, attachment_id: str
    ) -> AttachmentContent:
        message = await self.get_message(message_id)
        for attachment in message.attachments:
            if attachment.id == attachment_id:
                data = self.attachment_data.get((message_id, attachment_id), b"")
                return AttachmentContent(
                    filename=attachment.filename,
                    content_type=attachment.content_type,
                    data=data,
                )
        raise NotFoundError(f"attachment {attachment_id} not found")

    async def get_raw(self, message_id: str) -> bytes:
        message = await self.get_message(message_id)
        body = message.text_body or ""
        return f"Subject: {message.subject or ''}\r\n\r\n{body}".encode()

    async def _update_one(
        self, message_id: str, changes: MessageUpdate
    ) -> MessageSummary:
        message = await self.get_message(message_id)
        fields = changes.model_dump(exclude_none=True)
        known = {folder.id for folder in self.folders}
        for folder_id in fields.get("folder_ids", []):
            if folder_id not in known:
                raise NotFoundError(f"folder {folder_id} not found")
        if "keywords" in fields:
            fields["keywords"] = sorted({k.lower() for k in fields["keywords"]})
        updated = message.model_copy(update=fields)
        self.messages[self.messages.index(message)] = updated
        return MessageSummary.model_validate(updated.model_dump())

    async def _delete_one(
        self, message_id: str, permanent: bool
    ) -> MessageSummary | None:
        message = await self.get_message(message_id)
        if permanent:
            self.messages.remove(message)
            return None
        trash = next((f.id for f in self.folders if f.role is FolderRole.TRASH), None)
        if trash is None:
            raise ConflictError(
                "the account has no trash folder: delete with permanent=true"
            )
        if trash in message.folder_ids:
            raise ConflictError(
                "the message is in the trash already: delete with permanent=true"
            )
        moved = message.model_copy(update={"folder_ids": [trash]})
        self.messages[self.messages.index(message)] = moved
        return MessageSummary.model_validate(moved.model_dump())

    async def send(self, raw: bytes, sender: str, recipients: list[str]) -> SentMessage:
        """Records what was sent in ``outbox`` and keeps a copy in the sent
        folder."""
        self.outbox.append((sender, list(recipients), raw))
        sent = next((f.id for f in self.folders if f.role is FolderRole.SENT), None)
        if sent is None:
            return SentMessage()
        copy = Message(
            id=f"sent_{len(self.outbox)}",
            folder_ids=[sent],
            subject=_header(raw, "Subject"),
            message_id_header=_header(raw, "Message-ID"),
        )
        self.messages.append(copy)
        return SentMessage(sent_copy=MessageSummary.model_validate(copy.model_dump()))

    async def create_folder(self, name: str, parent_id: str | None) -> Folder:
        if parent_id is not None:
            self._folder(parent_id)
        if any(f.name == name and f.parent_id == parent_id for f in self.folders):
            raise ConflictError(f"a folder {name} exists there already")
        folder = Folder(
            id=f"folder_{len(self.folders)}", name=name, parent_id=parent_id
        )
        self.folders.append(folder)
        return folder

    async def update_folder(
        self, folder_id: str, name: str, parent_id: str | None
    ) -> Folder:
        folder = self._folder(folder_id)
        if parent_id is not None:
            self._folder(parent_id)
        updated = folder.model_copy(update={"name": name, "parent_id": parent_id})
        self.folders[self.folders.index(folder)] = updated
        return updated

    async def delete_folder(self, folder_id: str) -> None:
        self.folders.remove(self._folder(folder_id))

    def _folder(self, folder_id: str) -> Folder:
        for folder in self.folders:
            if folder.id == folder_id:
                return folder
        raise NotFoundError(f"folder {folder_id} not found")

    async def update_messages(
        self, message_ids: list[str], changes: MessageUpdate
    ) -> dict[str, MessageSummary | MailboxApiError]:
        results: dict[str, MessageSummary | MailboxApiError] = {}
        for message_id in message_ids:
            try:
                results[message_id] = await self._update_one(message_id, changes)
            except MailboxApiError as exc:
                results[message_id] = exc
        return results

    async def delete_messages(
        self, message_ids: list[str], permanent: bool
    ) -> dict[str, MessageSummary | None | MailboxApiError]:
        results: dict[str, MessageSummary | None | MailboxApiError] = {}
        for message_id in message_ids:
            try:
                results[message_id] = await self._delete_one(message_id, permanent)
            except MailboxApiError as exc:
                results[message_id] = exc
        return results

    async def folder_states(self) -> dict[str, str]:
        return {
            f.id: ",".join(m.id for m in self.messages if f.id in m.folder_ids)
            for f in self.folders
        }

    async def folder_contents(self, folder_id: str) -> list[str]:
        return [m.id for m in self.messages if folder_id in m.folder_ids]

    async def message_headers(self, message_ids: list[str]) -> dict[str, str | None]:
        wanted = set(message_ids)
        return {m.id: m.message_id_header for m in self.messages if m.id in wanted}

    async def wait_for_change(self, timeout: float) -> bool:
        raise NotSupportedError("the memory provider does not push changes")

    async def verify(self) -> None:
        return None

    async def close(self) -> None:
        return None


def _header(raw: bytes, name: str) -> str | None:
    value = BytesHeaderParser().parsebytes(raw).get(name)
    return str(value) if value is not None else None
