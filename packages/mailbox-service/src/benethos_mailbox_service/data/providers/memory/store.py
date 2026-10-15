"""What the in-memory mailbox holds, as its parts read and change it. The
adapter holds it itself, where tests look at it."""

from __future__ import annotations

from typing import Protocol

from ....errors import missing, missing_message
from ...models import Folder, FolderRole, Message
from .. import rules


class Store(Protocol):
    folders: list[Folder]
    messages: list[Message]
    # Whether a message may sit in several folders.
    labels: bool
    attachment_data: dict[tuple[str, str], bytes]
    # The source of every stored draft, by id.
    raws: dict[str, bytes]
    drafts_saved: int
    # (sender, recipients, raw) of every send.
    outbox: list[tuple[str, list[str], bytes]]


def message(store: Store, message_id: str) -> Message:
    for found in store.messages:
        if found.id == message_id:
            return found
    raise missing_message(message_id)


def folder(store: Store, folder_id: str) -> Folder:
    for found in store.folders:
        if found.id == folder_id:
            return found
    raise missing("folder", folder_id)


def role_folder(store: Store, role: FolderRole) -> str:
    return rules.require_role_folder(store.folders, role).id
