"""An activity: something an agent did, as one line of the log.

One sentence per activity, in the past tense (docs/mailbox-agents/LOGGING.md section 3):
``<agent> <did what> <to which>[: <why>]``. A class of the catalogue says
the middle part in ``says``, the rest comes from here. ``record`` writes
the line under the activity's own logger, at its level, and builds it
only when that level is written.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import ClassVar

from benethos_mailbox_common.values import text as text_values

from .output import PACKAGE

__all__ = ["Activity", "Failure", "describe", "record"]


@dataclass(frozen=True, slots=True, kw_only=True)
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
        # Named, not super() alone: a slotted dataclass is made anew, and
        # before Python 3.14 super() would still name the class before it.
        super(Activity, cls).__init_subclass__(**kwargs)
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


@dataclass(frozen=True, slots=True, kw_only=True)
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
        log.log(activity.level, "%s", text_values.escaped(activity.line()))


def describe(error: BaseException) -> str:
    """What a line may say about ``error``: its class, and its code if any.
    Never its message, which may quote what an upstream answered."""
    code = getattr(error, "code", None)
    name = type(error).__name__
    return f"{name}({code})" if isinstance(code, str) and code else name
