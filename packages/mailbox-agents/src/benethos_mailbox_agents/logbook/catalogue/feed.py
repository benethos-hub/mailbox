"""The change feed of the mailbox service, and the backfill beside it."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import ClassVar

from benethos_mailbox_common.values import text as text_values

from ..activity import Activity


@dataclass(frozen=True, kw_only=True)
class Read(Activity):
    name: ClassVar[str] = "read"

    changes: int
    selected: int

    def says(self) -> str:
        return (
            f"read {text_values.plural(self.changes, 'change')} from the feed "
            f"and selected {self.selected}"
        )


@dataclass(frozen=True, kw_only=True)
class Expired(Activity):
    """The service no longer knows the stored cursor. The feed starts anew
    and a backfill covers the gap."""

    name: ClassVar[str] = "expired"
    level: ClassVar[int] = logging.WARNING

    def says(self) -> str:
        return "found its place in the feed expired and starts anew"


@dataclass(frozen=True, kw_only=True)
class Backfilled(Activity):
    name: ClassVar[str] = "backfilled"

    messages: int
    days: int

    def says(self) -> str:
        return (
            f"backfilled {text_values.plural(self.messages, 'message')} "
            f"of the last {text_values.plural(self.days, 'day')}"
        )
