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
from typing import Any

from .data.secrets import redact

PACKAGE = __name__.rpartition(".")[0]
FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
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
    arguments and a traceback alike."""

    def format(self, record: logging.LogRecord) -> str:
        return redact.redact(super().format(record))


def log_config(level: str, book: logging.Handler | None = None) -> dict[str, Any]:
    """The configuration for ``uvicorn.run(log_config=...)``, as
    ``logging.config.dictConfig`` takes it. ``book`` keeps the newest
    lines for the log page as well."""
    number = LEVELS[level.lower()]
    plain = {"()": Redacting, "fmt": FORMAT, "datefmt": DATE_FORMAT}
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
