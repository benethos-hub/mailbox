"""The log of ``serve``: one stream and one format for uvicorn and the
service.

Without its own configuration uvicorn sets up only its loggers. The
service's records then had no handler: below WARNING they were dropped,
above they came without time or source. Libraries log from WARNING on,
so a debug level shows the service without the IMAP commands of a
library.
"""

from __future__ import annotations

import logging
from typing import Any

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


def log_config(level: str) -> dict[str, Any]:
    """The configuration for ``uvicorn.run(log_config=...)``, as
    ``logging.config.dictConfig`` takes it."""
    number = LEVELS[level.lower()]
    plain = {"format": FORMAT, "datefmt": DATE_FORMAT}
    return {
        "version": 1,
        "disable_existing_loggers": False,
        # uvicorn sets the colours of these two by name when asked to.
        "formatters": {"default": plain, "access": plain},
        "handlers": {
            "stderr": {
                "class": "logging.StreamHandler",
                "formatter": "default",
                "stream": "ext://sys.stderr",
            }
        },
        "root": {"level": logging.WARNING, "handlers": ["stderr"]},
        "loggers": {
            name: {"level": number, "handlers": [], "propagate": True}
            for name in (PACKAGE, "uvicorn", "uvicorn.error", "uvicorn.access")
        },
    }
