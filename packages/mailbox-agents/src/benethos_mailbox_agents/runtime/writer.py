"""What the executor needs of the mailbox: the message as it is now,
the folders of its account, and the writes the executor may make."""

from __future__ import annotations

from typing import Protocol

from ..records import FolderRef, MailMessage, MessageRef

__all__ = ["Writer"]


class Writer(Protocol):
    """What the executor needs of the mailbox."""

    async def message(self, ref: MessageRef) -> MailMessage:
        """The message as it is now."""

    async def folder_at(self, account_id: str, path: str) -> FolderRef | None:
        """The folder at ``path``, or None when there is none."""

    async def folders(
        self, account_id: str, *, fresh: bool = False
    ) -> dict[str, FolderRef]:
        """The folders of an account by id, read anew with ``fresh``."""

    async def add_keyword(self, ref: MessageRef, keyword: str) -> None:
        """Set ``keyword`` on the message."""

    async def remove_keyword(self, ref: MessageRef, keyword: str) -> None:
        """Take ``keyword`` off the message."""

    async def move(self, ref: MessageRef, folder_id: str) -> None:
        """Move the message into the folder of ``folder_id``."""

    async def create_folder(self, account_id: str, path: str) -> FolderRef:
        """Make the folder at ``path``, its parent there already."""
