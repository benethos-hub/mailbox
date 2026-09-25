"""The contract every provider adapter fulfils."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from enum import StrEnum
from typing import Protocol

from pydantic import SecretStr

from ...errors import MailboxServiceError
from ..models import (
    AttachmentContent,
    Folder,
    Message,
    MessageFilter,
    MessageSummary,
    MessageUpdate,
    Page,
    SentMessage,
)

# Hands an adapter one stored credential by field name, decrypted at the
# moment of the call. Adapters call it right before a login and keep nothing.
CredentialReader = Callable[[str], SecretStr]

# An account's connection settings: host, port, security and the like.
# Never a secret: those come through the ``CredentialReader``.
ProviderSettings = Mapping[str, str | int | bool]


class TokenSource(Protocol):
    """Hands an OAuth adapter a valid access token, refreshed when it runs
    out. The token lives in memory only. What keeps it valid is stored by
    whoever made the source."""

    async def access_token(self) -> SecretStr:
        """A token valid for at least another minute."""
        ...

    def reject(self) -> None:
        """The provider refused the token before it ran out, e.g. after a
        revocation: the next call fetches a new one."""
        ...


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

    async def create_folder(self, name: str, parent_id: str | None) -> Folder:
        """A new folder, subscribed where the provider knows subscriptions."""
        ...

    async def update_folder(
        self, folder_id: str, name: str, parent_id: str | None
    ) -> Folder:
        """Rename or move. The folder's id may change with its name."""
        ...

    async def delete_folder(self, folder_id: str) -> None: ...

    async def list_messages(
        self,
        folder_id: str | None,
        *,
        limit: int,
        cursor: str | None,
        search: MessageFilter | None = None,
    ) -> Page[MessageSummary]:
        """Newest first. ``search`` narrows the list. A cursor belongs to
        the same folder and search. Without a folder: every folder of the
        account where the provider can list across them (Microsoft), else
        the inbox (IMAP)."""
        ...

    async def get_message(self, message_id: str) -> Message: ...

    async def get_attachment(
        self, message_id: str, attachment_id: str
    ) -> AttachmentContent: ...

    async def get_raw(self, message_id: str) -> bytes:
        """The message source as RFC 822 bytes."""
        ...

    async def send(self, raw: bytes, sender: str, recipients: list[str]) -> SentMessage:
        """Send a composed message, and keep a copy where the provider does
        not do that itself. Once the message is out it does not fail: a
        client would send again."""
        ...

    # --- drafts, with DRAFTS ----------------------------------------------------
    # A draft id names a message the provider keeps as a draft, on IMAP one
    # in the folder with the drafts role. Any other id is not found, so that
    # the draft operations reach drafts only.

    async def list_drafts(
        self, *, limit: int, cursor: str | None
    ) -> Page[MessageSummary]: ...

    async def save_draft(self, raw: bytes, replaces: str | None) -> MessageSummary:
        """Store a composed draft, then remove the draft it ``replaces``.
        The draft as stored. Its id may differ from ``replaces``."""
        ...

    async def get_draft(self, draft_id: str) -> bytes:
        """The draft's source as RFC 822 bytes."""
        ...

    async def delete_draft(self, draft_id: str) -> None:
        """Remove a draft for good, as mail clients do once it is sent."""
        ...

    async def update_messages(
        self, message_ids: list[str], changes: MessageUpdate
    ) -> dict[str, MessageSummary | MailboxServiceError]:
        """Change flags and keywords, or move, of every message. Per id the
        message as it is now (after a move its id names the new place), or
        why not. A failed login or connection raises instead."""
        ...

    async def delete_messages(
        self, message_ids: list[str], permanent: bool
    ) -> dict[str, MessageSummary | None | MailboxServiceError]:
        """Into the trash, or for good. Per id the message in the trash
        where it is known, None when it is gone or not found there at once,
        or why not. A failed login or connection raises instead."""
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

    async def flag_changes(
        self, folder_id: str, since: str, message_ids: list[str]
    ) -> list[str]:
        """Those of ``message_ids``, all in the folder, whose flags changed
        since the folder had the state ``since``. Empty where the provider
        cannot tell."""
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
