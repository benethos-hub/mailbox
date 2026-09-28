"""The service log on a page (docs/UI.md 6.5): the newest lines of this
process. They name users, client addresses and accounts, so only
``admin`` on every account reads them."""

from __future__ import annotations

import logging

from ...data.logbook import LogBook, LogEntry
from ...data.models import Page
from ...errors import BadRequestError
from ..activity import ActivityLog, Actor
from ..activity.catalogue.service import LogRead
from ..rights import Access

# The levels a reader may ask for, from the least.
LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
}


class ServiceLog:
    def __init__(self, book: LogBook, activity: ActivityLog | None = None) -> None:
        self._book = book
        self._activity = activity or ActivityLog()

    def lines(
        self,
        access: Access,
        *,
        text: str | None = None,
        level: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> Page[LogEntry]:
        """The lines newest first, those with ``text`` in their message or
        source and at ``level`` or above. ``cursor`` continues after the
        line it names."""
        access.require("read_service_log")
        if level is not None and level not in LEVELS:
            raise BadRequestError(f"no log level {level}")
        if cursor is None:
            # Once per visit and search, not for every further page.
            self._activity.record(LogRead(by=Actor.of(access)))
        least = LEVELS.get(level or "", 0)
        wanted = text.casefold() if text else None
        before = _before(cursor)
        found = [
            entry
            for entry in self._book.newest_first()
            if entry.seq < before
            and entry.levelno >= least
            and (
                wanted is None
                or wanted in entry.message.casefold()
                or wanted in entry.source.casefold()
            )
        ]
        more = len(found) > limit
        shown = found[:limit]
        return Page(items=shown, next_cursor=str(shown[-1].seq) if more else None)


def _before(cursor: str | None) -> int:
    if cursor is None:
        return 2**63
    try:
        return int(cursor)
    except ValueError:
        raise BadRequestError("invalid cursor") from None
