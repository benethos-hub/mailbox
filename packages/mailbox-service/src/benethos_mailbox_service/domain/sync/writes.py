"""Our own changes to the messages of an account, counted, so a sync pass
can tell that one overtook it (CONCEPT 4.1).

A pass reads the folders one after another and then writes what it saw
into the index. A move of ours that falls between those reads leaves the
pass with a view the move has made old. Written, it would drop the id of
the moved message or give its old place a new id. So the pass notes how
many of our changes were done before it read, and applies nothing when
one runs or ended since.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass


@dataclass
class _Count:
    # Changes between the provider's call and the index following it.
    running: int = 0
    # Changes done, and changes to the index outside a pass.
    done: int = 0


class OwnWrites:
    """Per account, our changes running now and those done. Kept in
    memory: a pass and the changes it must notice run in one process."""

    def __init__(self) -> None:
        self._counts: dict[str, _Count] = {}

    def _of(self, account_id: str) -> _Count:
        return self._counts.setdefault(account_id, _Count())

    def mark(self, account_id: str) -> int:
        """How many changes were done, before a pass reads."""
        return self._of(account_id).done

    def overtaken(self, account_id: str, mark: int) -> bool:
        """Whether a change runs now or ended since ``mark``."""
        count = self._of(account_id)
        return count.running > 0 or count.done != mark

    def done(self, account_id: str) -> None:
        """The index changed outside a pass."""
        self._of(account_id).done += 1

    @contextmanager
    def writing(self, account_id: str) -> Iterator[None]:
        """A change: from the provider's call to the index following it."""
        count = self._of(account_id)
        count.running += 1
        try:
            yield
        finally:
            count.running -= 1
            count.done += 1

    @contextmanager
    def pausing(self, account_id: str) -> Iterator[None]:
        """Inside ``writing``: a pass the change asks for itself does not
        count the change as running, or it would discard itself."""
        count = self._of(account_id)
        count.running -= 1
        try:
            yield
        finally:
            count.running += 1

    def forget(self, account_id: str) -> None:
        """An account is deleted."""
        self._counts.pop(account_id, None)
