"""Where the lines go: one handler on stderr, every line redacted.

A line is written as docs/mailbox-agents/LOGGING.md section 3 says, by
the lines of mailbox-common, as the service and the MCP server write
theirs: the time, the level, the source and the message. On a terminal
the line is in colour and the source short, elsewhere, in a container
log or the journal, plain text with the whole name of the logger.
Either way each line, a traceback included, passes ``redact`` of
mailbox-common before it is written: the second line of defence, after
the catalogue that has no field for a secret.
"""

from __future__ import annotations

import logging
from typing import TextIO

from benethos_mailbox_common.log import lines

__all__ = ["LIBRARIES", "PACKAGE", "configure"]

PACKAGE = __name__.split(".")[0]

# Held at WARNING whatever the level says. httpx names every request with
# its whole URL at INFO, and a URL of the mailbox service carries ids and
# query parameters this package writes down only through its own lines.
LIBRARIES = ("httpx", "httpcore")


def configure(
    level: str = "INFO", stream: TextIO | None = None, *, colours: bool | None = None
) -> None:
    """Send the package's lines at ``level`` and every other line at
    ``WARNING`` to ``stream``, stderr by default. ``colours`` defaults to
    whether the stream is a terminal."""
    lines.to_stream(PACKAGE, level, stream=stream, colours=colours)
    for name in LIBRARIES:
        logging.getLogger(name).setLevel(logging.WARNING)
