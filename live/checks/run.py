"""The outcome of a run, and waiting for something to happen."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


class Run:
    """The checks of one run: each printed as it happens, counted at the end."""

    def __init__(self) -> None:
        self.failures = 0

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        print(f"{'PASS' if ok else 'FAIL'}  {name}{f'  ({detail})' if detail else ''}")
        self.failures += not ok
        return ok

    def finish(self) -> int:
        """The closing line, and the exit code of the script."""
        print(f"\n{self.failures} failed" if self.failures else "\nall passed")
        return 1 if self.failures else 0


def polled(look: Callable[[], T], tries: int, pause: float) -> T | None:
    """What ``look`` finds, tried again after ``pause`` seconds until it finds
    something or ``tries`` are used up."""
    for attempt in range(tries):
        found = look()
        if found:
            return found
        if attempt + 1 < tries:
            time.sleep(pause)
    return None
