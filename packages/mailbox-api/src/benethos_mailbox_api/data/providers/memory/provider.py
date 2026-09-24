"""An in-memory provider for tests and local development. No network."""

from __future__ import annotations

from ....errors import NotFoundError
from ...models import (
    AttachmentContent,
    Folder,
    FolderRole,
    Message,
    MessageSummary,
    Page,
)
from ..base import Capability


class MemoryProvider:
    capabilities = frozenset({Capability.SEND, Capability.DRAFTS})

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

    async def verify(self) -> None:
        return None

    async def close(self) -> None:
        return None
