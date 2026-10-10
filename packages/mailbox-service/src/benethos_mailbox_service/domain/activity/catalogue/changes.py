"""The change feed (docs/LOGGING.md 5.5). A change itself is no
activity: only what the service does to the feed."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar

from benethos_mailbox_common.log import lines

from ....common.text import plural
from ..base import Activity


@dataclass(frozen=True, kw_only=True)
class ChangesPurged(Activity):
    """Changes older than the feed keeps are gone: a client or webhook
    that had not read them yet starts after them. The normal course, once
    an hour at most, so no warning."""

    name: ClassVar[str] = "purged"

    count: int
    before: datetime

    def says(self) -> str:
        return (
            f"purged {plural(self.count, 'change')} older than "
            f"{lines.log_time(self.before)} from the change log"
        )
