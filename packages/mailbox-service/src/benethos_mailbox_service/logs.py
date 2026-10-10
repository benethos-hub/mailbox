"""The log of ``serve``: one stream and one format for uvicorn and the
service.

Without its own configuration uvicorn sets up only its loggers. The
service's records then had no handler: below WARNING they were dropped,
above they came without time or source. Libraries log from WARNING on,
so a debug level shows the service without the IMAP commands of a
library. The lines are those of ``benethos_mailbox_common.log.lines``, a
secret the service holds masked in every one. The access line of
uvicorn is the service's own.
"""

from __future__ import annotations

import logging
from http import HTTPStatus
from typing import Any

from benethos_mailbox_common.log import lines

PACKAGE = __name__.rpartition(".")[0]
# As uvicorn colours a status: 2xx green, 3xx yellow, 4xx red, 5xx bold.
_STATUS_COLOURS = {1: "", 2: "\033[32m", 3: "\033[33m", 4: "\033[31m", 5: "\033[1;31m"}
# The access line of uvicorn: client, method, path, HTTP version, status.
_ACCESS_ARGS = 5


def source_of(name: str) -> str:
    """The source of a line as the console names it: ``domain.auth``."""
    return lines.short_source(name, PACKAGE)


def _access(record: logging.LogRecord) -> str | None:
    """An access line of uvicorn on a terminal: method, path, the status
    in colour, the client. None for any other record."""
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
    reset, dim = lines.RESET, lines.DIM
    return f"{method} {path} {colour}{status} {phrase}{reset} {dim}{client}{reset}"


class WithoutQuery(logging.Filter):
    """An access line with the path of the request alone. Its query holds
    what a person typed, such as search terms (docs/LOGGING.md section 4)."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) == _ACCESS_ARGS:
            path = args[2]
            if isinstance(path, str) and "?" in path:
                record.args = (*args[:2], path.partition("?")[0], *args[3:])
        return True


def log_config(
    level: str, book: logging.Handler | None = None, colours: bool | None = None
) -> dict[str, Any]:
    """The configuration for ``uvicorn.run(log_config=...)``, as
    ``logging.config.dictConfig`` takes it. ``book`` keeps the newest
    lines for the log page as well. ``colours`` gives the compact lines
    of ``Console``, by default on a terminal, with the access line of
    ``_access``. Elsewhere, in a container log or the journal, each line
    is plain text."""
    number = lines.LEVELS[level.lower()]
    line_format = {
        "()": lines.formatter,
        "package": PACKAGE,
        "colours": colours,
        "line_of": _access,
    }
    handlers: dict[str, Any] = {
        "stderr": {
            "class": "logging.StreamHandler",
            "formatter": "default",
            "stream": "ext://sys.stderr",
        }
    }
    if book is not None:
        handlers["book"] = {"()": lambda: book}
    loggers: dict[str, Any] = {
        name: {"level": number, "handlers": [], "propagate": True}
        for name in (PACKAGE, "uvicorn", "uvicorn.error", "uvicorn.access")
    }
    loggers["uvicorn.access"]["filters"] = ["without_query"]
    return {
        "version": 1,
        "disable_existing_loggers": False,
        # uvicorn sets the colours of these two by name when asked to.
        "formatters": {"default": line_format, "access": line_format},
        "filters": {"without_query": {"()": WithoutQuery}},
        "handlers": handlers,
        "root": {"level": logging.WARNING, "handlers": list(handlers)},
        "loggers": loggers,
    }
