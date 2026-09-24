"""The contract every provider adapter fulfils."""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol

from ..models import Folder, Message, MessageSummary, Page


class Capability(StrEnum):
    """What an adapter can do beyond the read-only core."""

    SEND = "send"
    DRAFTS = "drafts"
    THREADS = "threads"
    LABELS = "labels"  # a message can sit in several folders at once
    SERVER_SEARCH = "server_search"
    PUSH = "push"  # change notifications without polling


class MailProvider(Protocol):
    """One connected account at one provider."""

    capabilities: frozenset[Capability]

    async def list_folders(self) -> list[Folder]: ...

    async def list_messages(
        self,
        folder_id: str | None,
        *,
        limit: int,
        cursor: str | None,
        query: str | None,
        unread: bool | None,
    ) -> Page[MessageSummary]: ...

    async def get_message(self, message_id: str) -> Message: ...

    async def close(self) -> None: ...
