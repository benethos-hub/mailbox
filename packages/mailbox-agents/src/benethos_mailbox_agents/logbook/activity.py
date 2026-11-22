"""An activity: something an agent did, as one line of the log.

One sentence per activity, in the past tense (docs/mailbox-agents/LOGGING.md section 3):
``<agent> <did what> <to which>[: <why>]``. A class of the catalogue says
the middle part in ``says``, the rest comes from here. ``record`` writes
the line under the activity's own logger, at its level, and builds it
only when that level is written.
"""

from __future__ import annotations

import logging
import unicodedata
from dataclasses import dataclass
from typing import ClassVar

from .output import PACKAGE

__all__ = ["Activity", "Failure", "describe", "escaped", "plural", "record"]

# What ends a line or moves the cursor for a reader: the control
# characters, C1 among them, and the separators of lines and paragraphs.
# And a lone surrogate, which cannot be written to a terminal at all.
_BREAKS = frozenset({"Cc", "Zl", "Zp", "Cs"})

# What turns the direction of the text after it: the Arabic letter mark,
# the marks left to right and right to left, the embeddings and overrides,
# and the isolates. A sender or subject would turn a report around.
_BIDI = frozenset(
    map(chr, (0x061C, 0x200E, 0x200F, *range(0x202A, 0x202F), *range(0x2066, 0x206A)))
)


@dataclass(frozen=True, kw_only=True)
class Activity:
    """One activity. ``name`` is set by each class and stays when the class
    is renamed: an operator's filters know it (docs/mailbox-agents/LOGGING.md section
    6). ``area`` is the module of the catalogue the class is in. ``level`` is
    its level in the log.

    A field holds only what a line may carry: ids, states, counts,
    durations, codes and an error, which the line names by its class and
    code. Never a type that holds a piece of a mail or a secret.
    """

    area: ClassVar[str] = ""
    name: ClassVar[str] = ""
    level: ClassVar[int] = logging.INFO

    agent: str

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        cls.area = cls.__module__.rpartition(".")[2]

    @classmethod
    def source(cls) -> str:
        """``activity.<area>.<name>``, the logger the line is written to
        below the package's."""
        return f"activity.{cls.area}.{cls.name}"

    def says(self) -> str:
        """What the agent did to which, such as ``set message m1 to done``."""
        raise NotImplementedError

    def why(self) -> str | None:
        """The reason after a colon, when there is one."""
        return None

    def line(self) -> str:
        text = f"{self.agent} {self.says()}"
        why = self.why()
        return f"{text}: {why}" if why else text


@dataclass(frozen=True, kw_only=True)
class Failure(Activity):
    """An activity that failed, with its error, at ``WARNING`` unless the
    class says otherwise. The line names the error by ``describe``."""

    level: ClassVar[int] = logging.WARNING

    error: BaseException

    def why(self) -> str | None:
        return describe(self.error)


def record(activity: Activity) -> None:
    """Write the line of ``activity`` at its level, under its own logger.
    Below the level the line is not built."""
    log = logging.getLogger(f"{PACKAGE}.{activity.source()}")
    if log.isEnabledFor(activity.level):
        log.log(activity.level, "%s", escaped(activity.line()))


def describe(error: BaseException) -> str:
    """What a line may say about ``error``: its class, and its code if any.
    Never its message, which may quote what an upstream answered."""
    code = getattr(error, "code", None)
    name = type(error).__name__
    return f"{name}({code})" if isinstance(code, str) and code else name


def escaped(text: str) -> str:
    """``text`` as one line: each control character, line separator and
    mark of direction written as its escape, such as a line feed as
    backslash and n. Nothing an upstream chose then starts a line of its
    own, moves the cursor, sets the title of a terminal or turns the text
    around."""
    return "".join(
        ch.encode("unicode_escape").decode("ascii")
        if ch in _BIDI or unicodedata.category(ch) in _BREAKS
        else ch
        for ch in text
    )


def plural(count: int, word: str) -> str:
    """``1 message``, ``2 messages``."""
    return f"{count} {word}" if count == 1 else f"{count} {word}s"
