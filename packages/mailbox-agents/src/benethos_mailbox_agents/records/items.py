"""An open item: a message an agent follows until something happens to it,
by a deadline or without one."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from .mail import MessageRef

__all__ = ["KEYWORD_REMOVED", "MESSAGE_GONE", "OpenItem"]

# Why an item closed, where more than one module reads it. A person took
# the keyword off, so the item never starts again.
KEYWORD_REMOVED = "keyword_removed"
# The message is not there any more.
MESSAGE_GONE = "message_gone"


class OpenItem(BaseModel):
    """One row of the table ``open_items``, docs/mailbox-agents/concept/state.md.

    ``keyword_set`` says whether the agent has put its keyword on the
    message, so a keyword a person takes off can be told from one never
    set. ``closed`` and ``reason`` are empty while the item is open.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    ref: MessageRef
    thread_id: str | None
    opened: datetime
    due: datetime
    keyword_set: bool = False
    closed: datetime | None = None
    reason: str | None = None

    @property
    def is_open(self) -> bool:
        return self.closed is None
