"""The change feed (docs/LOGGING.md 5.5). A change itself is no
activity: only what the service does to the feed."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from ..base import Purged


@dataclass(frozen=True, kw_only=True)
class ChangesPurged(Purged):
    """Changes older than the feed keeps are gone: a client or webhook
    that had not read them yet starts after them. The normal course, once
    an hour at most, so no warning."""

    name: ClassVar[str] = "purged"
    record: ClassVar[str] = "change"
    purged_from: ClassVar[str] = "the change log"
