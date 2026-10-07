"""Text as people read it: on one line, and counted in words.

What ends a line to a reader is wider than what ends a line on the wire.
A reader of the log or of a header stops at CR and LF, at the other
control characters and at the line breaks beyond ASCII that
``str.splitlines`` breaks on. A protocol of lines, such as IMAP, POP3 or
SMTP, ends a command at CR, LF and NUL only, and carries every other
character as data.
"""

from __future__ import annotations

import re

# What ends a line to a reader: every control character, the line breaks
# beyond ASCII, U+2028 among them.
_BREAKS = re.compile(r"[\x00-\x1f\x7f\x85  ]")
_RUNS = re.compile(_BREAKS.pattern + "+")
# What ends a command or a value of a protocol of lines.
_LINE_ENDS = re.compile(r"[\r\n\x00]")


def escaped(text: str) -> str:
    """``text`` as one line: each break written as its escape, such as a
    line feed as backslash and n. For the log, where a name a caller chose
    must not start a line of its own."""
    return _BREAKS.sub(lambda m: m.group().encode("unicode_escape").decode(), text)


def joined(text: str) -> str:
    """``text`` as one line: each run of breaks becomes a space. For a
    header, which must not hold a break, and which a person reads."""
    return _RUNS.sub(" ", text)


def has_break(text: str) -> bool:
    """Whether ``text`` holds anything that ends a line to a reader."""
    return _BREAKS.search(text) is not None


def ends_line(*values: str) -> bool:
    """Whether any of ``values`` would end a command of a protocol of
    lines and start one of the caller's choosing."""
    return any(_LINE_ENDS.search(value) for value in values)


def plural(count: int, word: str) -> str:
    """``1 webhook``, ``2 webhooks``."""
    return f"{count} {word}" if count == 1 else f"{count} {word}s"
