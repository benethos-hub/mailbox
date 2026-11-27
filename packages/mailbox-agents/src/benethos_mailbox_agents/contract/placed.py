"""``Placed``: a message as an action sees it, where it lies and what it
carries, nothing it says. Two kinds of agent use it: ``categorization``
for the actions of its list, an actor for all it sees of a message. See
docs/mailbox-agents/concept/agent-contract.md."""

from __future__ import annotations

from dataclasses import dataclass

from ..records import FolderRef, MailMessage, MessageRef

__all__ = ["Placed"]


@dataclass(frozen=True, slots=True)
class Placed:
    """Where a message lies and what it carries, as an action sees it:
    its ids, its folders by path and role, its keywords. Nothing it says,
    nothing of its sender."""

    ref: MessageRef
    folders: tuple[FolderRef, ...]
    keywords: tuple[str, ...]

    @classmethod
    def of(cls, message: MailMessage) -> Placed:
        return cls(ref=message.ref, folders=message.folders, keywords=message.keywords)

    @property
    def in_inbox(self) -> bool:
        return any(folder.role == "inbox" for folder in self.folders)

    @property
    def own_folder(self) -> str | None:
        """The path of the folder it lies in when that folder has no role,
        as one the owner made, else None."""
        found = [folder for folder in self.folders if folder.role is None]
        return found[0].path if len(self.folders) == 1 and found else None
