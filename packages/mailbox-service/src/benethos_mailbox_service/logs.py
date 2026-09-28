"""The log of ``serve``: one stream and one format for uvicorn and the
service.

Without its own configuration uvicorn sets up only its loggers. The
service's records then had no handler: below WARNING they were dropped,
above they came without time or source. Libraries log from WARNING on,
so a debug level shows the service without the IMAP commands of a
library. A secret the service holds is masked in every line
(``data/secrets/redact.py``).
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime
from http import HTTPStatus
from typing import Any

from .data.secrets import redact

PACKAGE = __name__.rpartition(".")[0]
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


class Redacting(logging.Formatter):
    """Each line as written, a noted secret masked: in the message, its
    arguments and a traceback alike. The time to the millisecond with
    its offset, since a line may be read far from where it was written:
    ``2026-09-28 10:12:22.123+02:00``."""

    def format(self, record: logging.LogRecord) -> str:
        return redact.redact(super().format(record))

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        return _moment(record).isoformat(sep=" ", timespec="milliseconds")


def _moment(record: logging.LogRecord) -> datetime:
    """When the record was made, in the local time of this machine."""
    return datetime.fromtimestamp(record.created).astimezone()


# ANSI colours, for a terminal only.
_RESET = "\033[0m"
_DIM = "\033[2m"
_LEVEL_COLOURS = {
    logging.DEBUG: "\033[34m",
    logging.INFO: "\033[32m",
    logging.WARNING: "\033[33m",
    logging.ERROR: "\033[31m",
    logging.CRITICAL: "\033[1;31m",
}
_SOURCE = "\033[36m"
# As uvicorn colours a status: 2xx green, 3xx yellow, 4xx red, 5xx bold.
_STATUS_COLOURS = {1: "", 2: "\033[32m", 3: "\033[33m", 4: "\033[31m", 5: "\033[1;31m"}
# The access line of uvicorn: client, method, path, HTTP version, status.
_ACCESS_ARGS = 5


class Console(Redacting):
    """A line for a person at a terminal: the time dim, the level
    in colour, the source short, an access line as method, path and the
    status in colour."""

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        """Date and time to the millisecond, local, without the offset
        a person at this machine knows."""
        moment = _moment(record)
        return f"{moment:%Y-%m-%d %H:%M:%S}.{moment.microsecond // 1000:03d}"

    def format(self, record: logging.LogRecord) -> str:
        colour = _LEVEL_COLOURS.get(record.levelno, "")
        head = (
            f"{_DIM}{self.formatTime(record)}{_RESET} "
            f"{colour}{record.levelname:<8}{_RESET}"
            f"{_SOURCE}{short_source(record.name):<14}{_RESET} "
        )
        text = _access(record) or record.getMessage()
        if record.exc_info:
            text += "\n" + self.formatException(record.exc_info)
        return redact.redact(head + text)


def short_source(name: str) -> str:
    """``domain.auth`` for the service's own loggers, ``http`` for the
    access log, ``uvicorn`` for the server."""
    if name == "uvicorn.access":
        return "http"
    if name.startswith("uvicorn"):
        return "uvicorn"
    return name.removeprefix(f"{PACKAGE}.")


def _access(record: logging.LogRecord) -> str | None:
    if record.name != "uvicorn.access" or not isinstance(record.args, tuple):
        return None
    if len(record.args) != _ACCESS_ARGS:
        return None
    client, method, path, _, status = record.args
    if not isinstance(status, int):
        return None
    try:
        phrase = HTTPStatus(status).phrase
    except ValueError:
        phrase = ""
    colour = _STATUS_COLOURS.get(status // 100, "")
    return f"{method} {path} {colour}{status} {phrase}{_RESET} {_DIM}{client}{_RESET}"


def colours_wanted() -> bool:
    """Colours on a terminal, unless ``NO_COLOR`` is set (no-color.org)."""
    return sys.stderr.isatty() and "NO_COLOR" not in os.environ


def log_config(
    level: str, book: logging.Handler | None = None, colours: bool | None = None
) -> dict[str, Any]:
    """The configuration for ``uvicorn.run(log_config=...)``, as
    ``logging.config.dictConfig`` takes it. ``book`` keeps the newest
    lines for the log page as well. ``colours`` gives the compact lines
    of ``Console``, by default on a terminal. Elsewhere, in a container
    log or the journal, each line is plain text."""
    number = LEVELS[level.lower()]
    if colours is None:
        colours = colours_wanted()
    plain = {"()": Console} if colours else {"()": Redacting, "fmt": FORMAT}
    handlers: dict[str, Any] = {
        "stderr": {
            "class": "logging.StreamHandler",
            "formatter": "default",
            "stream": "ext://sys.stderr",
        }
    }
    if book is not None:
        handlers["book"] = {"()": lambda: book}
    return {
        "version": 1,
        "disable_existing_loggers": False,
        # uvicorn sets the colours of these two by name when asked to.
        "formatters": {"default": plain, "access": plain},
        "handlers": handlers,
        "root": {"level": logging.WARNING, "handlers": list(handlers)},
        "loggers": {
            name: {"level": number, "handlers": [], "propagate": True}
            for name in (PACKAGE, "uvicorn", "uvicorn.error", "uvicorn.access")
        },
    }
