"""Where the lines go: one handler on stderr, every line redacted.

A line is written as docs/mailbox-agents/LOGGING.md section 3 says: the time, the level,
the source and the message. On a terminal the line is in colour and the
source short, elsewhere, in a container log or the journal, plain text
with the whole name of the logger. Either way each line, a traceback
included, passes ``errors.redact`` before it is written: the second line
of defence, after the catalogue that has no field for a secret.
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime
from typing import TextIO

from ..errors import redact

__all__ = [
    "FORMAT",
    "LIBRARIES",
    "PACKAGE",
    "SOURCE_WIDTH",
    "Console",
    "Plain",
    "colours_wanted",
    "configure",
    "log_time",
]

PACKAGE = __name__.split(".")[0]

# Held at WARNING whatever the level says. httpx names every request with
# its whole URL at INFO, and a URL of the mailbox service carries ids and
# query parameters this package writes down only through its own lines.
LIBRARIES = ("httpx", "httpcore")

FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"

# The column of the source on a terminal: ``activity.<area>.<name>`` has
# 32 characters at most (docs/mailbox-agents/LOGGING.md section 6).
SOURCE_WIDTH = 32

# ANSI colours, for a terminal only.
_RESET = "\033[0m"
_DIM = "\033[2m"
_SOURCE = "\033[36m"
_LEVEL_COLOURS = {
    logging.DEBUG: "\033[34m",
    logging.INFO: "\033[32m",
    logging.WARNING: "\033[33m",
    logging.ERROR: "\033[31m",
    logging.CRITICAL: "\033[1;31m",
}

# Marks the handler this module installed, so configuring twice replaces it
# rather than printing every line twice.
_MARK = "_mailbox_agents_logbook"


def log_time(value: datetime) -> str:
    """A time as every line writes it: ISO 8601, the local time of this
    machine, to the millisecond, with the offset.
    ``2026-11-18T10:12:22.123+01:00``."""
    return value.astimezone().isoformat(timespec="milliseconds")


def colours_wanted(stream: TextIO) -> bool:
    """Colours on a terminal, unless ``NO_COLOR`` is set (no-color.org)."""
    isatty = getattr(stream, "isatty", None)
    return bool(isatty and isatty()) and not os.environ.get("NO_COLOR")


class Plain(logging.Formatter):
    """A line as written to a file or a container log, a registered secret
    masked in the message, its arguments and a traceback alike."""

    def __init__(self) -> None:
        super().__init__(FORMAT)

    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))

    def formatTime(  # noqa: N802 - the name logging calls
        self, record: logging.LogRecord, datefmt: str | None = None
    ) -> str:
        return log_time(datetime.fromtimestamp(record.created).astimezone())


class Console(Plain):
    """A line for a person at a terminal: the time dim, the level in
    colour, the source without the package's name in front."""

    def format(self, record: logging.LogRecord) -> str:
        colour = _LEVEL_COLOURS.get(record.levelno, "")
        source = record.name.removeprefix(f"{PACKAGE}.")
        text = (
            f"{_DIM}{self.formatTime(record)}{_RESET} "
            f"{colour}{record.levelname:<8}{_RESET} "
            f"{_SOURCE}{source:<{SOURCE_WIDTH}}{_RESET} "
            f"{record.getMessage()}"
        )
        if record.exc_info:
            text += "\n" + self.formatException(record.exc_info)
        return redact(text)


def configure(
    level: str = "INFO", stream: TextIO | None = None, *, colours: bool | None = None
) -> None:
    """Send the package's lines at ``level`` and every other line at
    ``WARNING`` to ``stream``, stderr by default. ``colours`` defaults to
    whether the stream is a terminal."""
    target = stream or sys.stderr
    if colours is None:
        colours = colours_wanted(target)
    handler = logging.StreamHandler(target)
    handler.setFormatter(Console() if colours else Plain())
    setattr(handler, _MARK, True)
    root = logging.getLogger()
    for old in [h for h in root.handlers if getattr(h, _MARK, False)]:
        root.removeHandler(old)
    root.addHandler(handler)
    root.setLevel(logging.WARNING)
    logging.getLogger(PACKAGE).setLevel(level.upper())
    for name in LIBRARIES:
        logging.getLogger(name).setLevel(logging.WARNING)
