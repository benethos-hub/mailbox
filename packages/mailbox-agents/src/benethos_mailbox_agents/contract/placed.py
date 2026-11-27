"""``Placed``: a message as an action sees it, where it lies and what it
carries, nothing it says. Two kinds of agent use it: ``categorization``
for the actions of its list, an actor for all it sees of a message. See
docs/mailbox-agents/concept/agent-contract.md."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal

from ..records import FolderRef, MailMessage, MessageRef

__all__ = ["Placed"]


@dataclass(frozen=True, slots=True)
class Placed:
    """Where a message lies and what it carries, as an action sees it:
    its ids, its folders by path and role, its keywords, and what the
    receiving server stated about the domain of its sender. Nothing it
    says. Of its sender only whether it is one of some addresses: the
    address itself is held out of ``repr`` and of a comparison."""

    ref: MessageRef
    folders: tuple[FolderRef, ...]
    keywords: tuple[str, ...]
    sender_check: Literal["pass", "fail", "unknown"] = "unknown"
    from_address: str | None = field(default=None, repr=False, compare=False)

    @classmethod
    def of(cls, message: MailMessage) -> Placed:
        return cls(
            ref=message.ref,
            folders=message.folders,
            keywords=message.keywords,
            sender_check=message.sender_check,
            from_address=message.sender.email if message.sender else None,
        )

    def sent_by(self, addresses: Iterable[str]) -> bool:
        """Whether the message came from one of ``addresses``, case aside."""
        if self.from_address is None:
            return False
        found = self.from_address.casefold()
        return any(found == address.casefold() for address in addresses)

    @property
    def in_inbox(self) -> bool:
        return any(folder.role == "inbox" for folder in self.folders)

    @property
    def own_folder(self) -> str | None:
        """The path of the folder it lies in when that folder has no role,
        as one the owner made, else None."""
        found = [folder for folder in self.folders if folder.role is None]
        return found[0].path if len(self.folders) == 1 and found else None
