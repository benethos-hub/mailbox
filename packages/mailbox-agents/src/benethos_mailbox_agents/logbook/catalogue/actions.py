"""What the executor did with an action an agent asked for. ``why`` is the
agent's short code for the action, such as ``due``: a word of code,
never anything of the mail."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from ..activity import Activity, Failure


@dataclass(frozen=True, kw_only=True)
class Done(Activity):
    """The action was carried out on the message, and recorded."""

    name: ClassVar[str] = "done"

    message_id: str
    action: str
    stage: str
    reason: str

    def says(self) -> str:
        return (
            f"carried out {self.action} on message {self.message_id} "
            f"in stage {self.stage}"
        )

    def why(self) -> str | None:
        return self.reason or None


@dataclass(frozen=True, kw_only=True)
class Recorded(Done):
    """The action was recorded, not carried out: the stage did not allow
    it, the agent asked it to be held, as a group of ``sorting`` with
    ``hold`` does also in ``full``, or it comes after a folder or move
    that was recorded only."""

    name: ClassVar[str] = "recorded"

    def says(self) -> str:
        return (
            f"recorded {self.action} on message {self.message_id} "
            f"in stage {self.stage} without carrying it out"
        )


@dataclass(frozen=True, kw_only=True)
class Kept(Activity):
    """A move of a message the agent moved once already: the folder the
    owner chose since stands, and the move is not taken."""

    name: ClassVar[str] = "kept"

    message_id: str

    def says(self) -> str:
        return (
            f"left message {self.message_id} where the owner put it, "
            "as it moved it once before"
        )


@dataclass(frozen=True, kw_only=True)
class Refused(Failure):
    """The executor or the mailbox service refused the action."""

    name: ClassVar[str] = "refused"

    message_id: str
    action: str

    def says(self) -> str:
        return f"was refused {self.action} on message {self.message_id}"
