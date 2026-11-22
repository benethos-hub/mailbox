"""The lines of a log, alike in every program of Mailbox
(docs/mailbox-service/LOGGING.md 6.9): the time, the level, where a line comes from and
the message, a noted secret masked (``redact``).

On a terminal a line is short and in colour, elsewhere, in a container
log or the journal, plain text. A program may write each line as one
JSON object instead (``Json``), for a log collector. What a program
logs, and its own kinds of lines such as the access line of a web
server, stay its own: it hands ``Console`` a ``line_of`` and ``Json`` a
``fields_of`` for them.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from collections.abc import Callable
from datetime import datetime
from typing import TextIO

from . import redact

FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
# As uvicorn names them. Its trace level is below debug.
LEVELS = {
    "critical": logging.CRITICAL,
    "error": logging.ERROR,
    "warning": logging.WARNING,
    "info": logging.INFO,
    "debug": logging.DEBUG,
    "trace": 5,
}

# ANSI colours, for a terminal only.
RESET = "\033[0m"
DIM = "\033[2m"
_LEVEL_COLOURS = {
    logging.DEBUG: "\033[34m",
    logging.INFO: "\033[32m",
    logging.WARNING: "\033[33m",
    logging.ERROR: "\033[31m",
    logging.CRITICAL: "\033[1;31m",
}
_SOURCE = "\033[36m"
# The column of the source: the longest name of an activity of the
# service, ``activity.<area>.<name>``, has 32 characters
# (docs/mailbox-service/LOGGING.md 7.2).
SOURCE_WIDTH = 32

# A program's own text for a record, None for the message as it is.
LineOf = Callable[[logging.LogRecord], str | None]
# A program's own fields of a record in a JSON line, None for none.
FieldsOf = Callable[[logging.LogRecord], dict[str, object] | None]


def log_time(value: datetime) -> str:
    """A time as every line of the log writes it, wherever it stands:
    ISO 8601, the local time of this machine, to the millisecond, with the
    offset. ``2026-09-28T10:12:22.123+02:00``."""
    return value.astimezone().isoformat(timespec="milliseconds")


def colours_wanted(stream: TextIO | None = None) -> bool:
    """Colours when ``stream``, stderr when None, is a terminal, unless
    ``NO_COLOR`` is set to a value that is not empty (no-color.org)."""
    target = sys.stderr if stream is None else stream
    return target.isatty() and not os.environ.get("NO_COLOR")


def short_source(name: str, package: str) -> str:
    """``domain.auth`` for the loggers of ``package``, ``http`` for the
    access log of uvicorn, ``uvicorn`` for the server."""
    if name == "uvicorn.access":
        return "http"
    if name.startswith("uvicorn"):
        return "uvicorn"
    return name.removeprefix(f"{package}.")


class Redacting(logging.Formatter):
    """Each line as written, a noted secret masked: in the message, its
    arguments and a traceback alike. The time as every line writes it
    (``log_time``)."""

    def __init__(self, fmt: str = FORMAT) -> None:
        super().__init__(fmt)

    def format(self, record: logging.LogRecord) -> str:
        return redact.redact(super().format(record))

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        return log_time(datetime.fromtimestamp(record.created).astimezone())


class Console(Redacting):
    """A line for a person at a terminal: the time dim, the level in
    colour, the source short (``short_source`` of ``package``), and the
    text ``line_of`` gives, else the message. The time as in every other
    line."""

    def __init__(self, package: str = "", line_of: LineOf | None = None) -> None:
        super().__init__()
        self._package = package
        self._line_of = line_of

    def format(self, record: logging.LogRecord) -> str:
        colour = _LEVEL_COLOURS.get(record.levelno, "")
        source = short_source(record.name, self._package)
        head = (
            f"{DIM}{self.formatTime(record)}{RESET} "
            f"{colour}{record.levelname:<8}{RESET} "
            f"{_SOURCE}{source:<{SOURCE_WIDTH}}{RESET} "
        )
        own = self._line_of(record) if self._line_of is not None else None
        text = own or record.getMessage()
        if record.exc_info:
            text += "\n" + self.formatException(record.exc_info)
        return redact.redact(head + text)


class Json(Redacting):
    """Each line as one JSON object, for a log collector: ``time`` as
    every line writes it, ``level``, ``source`` (the logger's whole
    name), ``message``, ``traceback`` where there is one, and the fields
    ``fields_of`` gives, which never replace these. A noted secret is
    masked in each text before it is encoded, since JSON writes quotes,
    backslashes and line breaks anew."""

    def __init__(self, fields_of: FieldsOf | None = None) -> None:
        super().__init__()
        self._fields_of = fields_of

    def format(self, record: logging.LogRecord) -> str:
        found: dict[str, object] = {
            "time": self.formatTime(record),
            "level": record.levelname,
            "source": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            found["traceback"] = self.formatException(record.exc_info)
        own = self._fields_of(record) if self._fields_of is not None else None
        for key, value in (own or {}).items():
            found.setdefault(key, value)
        masked = {
            key: redact.redact(value) if isinstance(value, str) else value
            for key, value in found.items()
        }
        return json.dumps(masked, ensure_ascii=False)


def formatter(
    package: str, *, colours: bool | None = None, line_of: LineOf | None = None
) -> logging.Formatter:
    """``Console`` where ``colours`` is true, by default on a terminal,
    else the plain ``Redacting``."""
    if colours is None:
        colours = colours_wanted()
    return Console(package, line_of) if colours else Redacting()


def stderr_handler(
    package: str, *, colours: bool | None = None, line_of: LineOf | None = None
) -> logging.Handler:
    """A handler that writes to stderr with the ``formatter`` that fits."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter(package, colours=colours, line_of=line_of))
    return handler
