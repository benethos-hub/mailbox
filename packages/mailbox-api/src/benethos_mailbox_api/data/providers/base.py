"""The contract every provider adapter fulfils."""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from typing import Protocol

from pydantic import SecretStr

from ..models import (
    AttachmentContent,
    Folder,
    Message,
    MessageSummary,
    MessageUpdate,
    Page,
)

# Hands an adapter one stored credential by field name, decrypted at the
# moment of the call. Adapters call it right before a login and keep nothing.
CredentialReader = Callable[[str], SecretStr]


class Capability(StrEnum):
    """What an adapter can do beyond the read-only core."""

    SEND = "send"
    DRAFTS = "drafts"
    THREADS = "threads"
    LABELS = "labels"  # a message can sit in several folders at once
    SERVER_SEARCH = "server_search"
    PUSH = "push"  # change notifications without polling, wait_for_change
    # A message keeps its id when it is moved. Without it the domain keeps an
    # id mapping (CONCEPT 4.1).
    STABLE_IDS = "stable_ids"


class MailProvider(Protocol):
    """One connected account at one provider.

    Message ids are the provider's own. Without ``STABLE_IDS`` they name a
    place, and the domain maps them to ids that survive a move.
    """

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

    async def get_attachment(
        self, message_id: str, attachment_id: str
    ) -> AttachmentContent: ...

    async def get_raw(self, message_id: str) -> bytes:
        """The message source as RFC 822 bytes."""
        ...

    async def update_message(
        self, message_id: str, changes: MessageUpdate
    ) -> MessageSummary:
        """Change flags and keywords. Returns the message as it is now."""
        ...

    # --- for the sync worker ---------------------------------------------------

    async def folder_states(self) -> dict[str, str]:
        """Every folder that holds messages, with an opaque state that
        changes whenever a message arrives in it or leaves it."""
        ...

    async def folder_contents(self, folder_id: str) -> list[str]:
        """The ids of every message in the folder."""
        ...

    async def message_headers(self, message_ids: list[str]) -> dict[str, str | None]:
        """The ``Message-ID`` header of each message. Messages that are gone
        are left out."""
        ...

    async def wait_for_change(self, timeout: float) -> bool:
        """Wait until the server reports a change in the inbox, at most
        ``timeout`` seconds. True if it did. Only with ``PUSH``."""
        ...

    async def verify(self) -> None:
        """Log in afresh and forget an earlier rejected login. Raises
        ``ProviderAuthError`` if the credential does not work."""
        ...

    async def close(self) -> None: ...
