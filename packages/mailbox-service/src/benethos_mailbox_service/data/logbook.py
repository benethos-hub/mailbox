"""The newest lines of the service log, in memory, for the log page.

A handler beside the one on stderr: it keeps the last ``KEPT`` records of
this process, a noted secret masked in each. Nothing is stored, so a
restart starts it empty.
"""

from __future__ import annotations

import itertools
import logging
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from benethos_mailbox_common.log import redact

KEPT = 1000

# Only its traceback text is used.
_TRACEBACK = logging.Formatter()


@dataclass(frozen=True)
class LogEntry:
    """One line of the log. ``seq`` counts up from the start."""

    seq: int
    at: datetime
    level: str
    levelno: int
    source: str
    message: str


class LogBook(logging.Handler):
    def __init__(
        self, kept: int = KEPT, source: Callable[[str], str] | None = None
    ) -> None:
        """``source`` names a line's source from its logger's name, as the
        console does. The assembly hands it in. Without it, the name."""
        super().__init__()
        self._source = source or (lambda name: name)
        self._entries: deque[LogEntry] = deque(maxlen=kept)
        self._seq = itertools.count(1)
        self._guard = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
            if record.exc_info:
                message += "\n" + _TRACEBACK.formatException(record.exc_info)
            at = datetime.fromtimestamp(record.created, UTC)
            with self._guard:
                self._entries.append(
                    LogEntry(
                        next(self._seq),
                        at,
                        record.levelname,
                        record.levelno,
                        self._source(record.name),
                        redact.redact(message),
                    )
                )
        except Exception:  # a log that fails must not fail the caller
            self.handleError(record)

    def newest_first(self) -> list[LogEntry]:
        with self._guard:
            return list(reversed(self._entries))
