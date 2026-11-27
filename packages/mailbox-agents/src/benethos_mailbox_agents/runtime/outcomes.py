"""What the executor plans and what becomes of an action, and the checks
of a folder path that need no state of it. :mod:`.actions` offers them."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from ..errors import ActionRefusedError

__all__ = ["Outcome", "Plan", "in_another_case", "well_formed"]


# The names a folder path may not hold between its slashes.
_NO_NAMES = frozenset({"", ".", ".."})


def well_formed(path: str) -> None:
    """Refuse a folder path that is not names between slashes: one that
    starts or ends with a slash, holds two in a row, or names ``.`` or
    ``..``. The executor holds to it whatever the agent may make."""
    if any(name in _NO_NAMES for name in path.split("/")):
        raise ActionRefusedError("the folder path is not names between slashes")


class Outcome(StrEnum):
    """What became of one action."""

    DONE = "done"  # the stage allows it, it was taken
    PRESENT = "present"  # its result was already there
    RECORDED = "recorded"  # the stage does not allow it, it was recorded only
    REFUSED = "refused"  # the executor or the mailbox service refused it
    # refused as the message lies in the trash, junk or spam, where the
    # owner put it: no failure, and no action of an agent comes there
    DISCARDED = "discarded"
    # a folder for a move not taken, not made, or a move of a message the
    # agent moved once before, where the owner's folder stands
    SKIPPED = "skipped"


def in_another_case(path: str, paths: Iterable[str]) -> bool:
    """Whether one of ``paths`` is ``path`` in another case only. The
    service would make such a folder as a second one (measured
    2026-11-18), so the executor neither makes it nor moves into it, and
    ``status`` names it."""
    return any(p != path and p.casefold() == path.casefold() for p in paths)


@dataclass(frozen=True)
class Plan:
    """One action as planned: the argument to record, what was there
    before, the target to send, and whether it is recorded only, as below
    a folder recorded and not made, whatever the stage."""

    argument: str
    before: dict[str, Any]
    target: str
    record_only: bool = False
