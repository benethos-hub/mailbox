"""A lock not taken again after the server was away: for a minute since
it went the server counts as still away, as the old session of the
program may still hold it. Past that another program took it."""

from __future__ import annotations

from typing import Any

import pytest

from benethos_mailbox_common.storage.errors import (
    StorageError,
    StorageUnavailableError,
)
from benethos_mailbox_common.storage.outage import LOCK_GRACE, Availability
from benethos_mailbox_common.storage.server_place import Server, ServerPlace

from .clocks import Seconds
from .shape_helpers import SHAPE


class _Session:
    """The one connection: it answers, and is let go when told."""

    def __init__(self) -> None:
        self.invalidated = 0

    def rollback(self) -> None:
        pass

    def commit(self) -> None:
        pass

    def execute(self, statement: object) -> None:
        pass

    def invalidate(self) -> None:
        self.invalidated += 1


def _away(clock: Seconds, held: list[bool]) -> tuple[ServerPlace, _Session, list]:
    place = ServerPlace(
        Server(host="db.example.test", port=5432, database="d", role="r", password="p"),
        SHAPE,
        clock,
    )
    session = _Session()
    place_: Any = place
    place_._connection = session
    place_._held = (7,)
    place_._locked = lambda connection, key: held.pop(0)
    reports: list[Availability] = []
    place.watch(reports.append)
    place_._outage.failed("connection")
    return place, session, reports


def test_a_lock_let_go_within_the_minute_is_taken_again() -> None:
    clock = Seconds()
    clock.now = 100.0
    place, session, reports = _away(clock, [False, True])

    clock.now += 1.5
    with pytest.raises(StorageUnavailableError):
        place.ready()
    assert session.invalidated == 1
    # The pause runs: nothing goes out.
    with pytest.raises(StorageUnavailableError):
        place.ready()
    clock.now += 2.5

    place.ready()

    assert reports[-1] == Availability(away=False, seconds=4.0, lock_lost=False)
    place.ready()


def test_a_lock_still_held_after_the_minute_was_taken() -> None:
    clock = Seconds()
    clock.now = 100.0
    place, _, reports = _away(clock, [False])

    clock.now += LOCK_GRACE + 1

    with pytest.raises(StorageError, match="took this database") as taken:
        place.ready()
    assert not isinstance(taken.value, StorageUnavailableError)
    assert reports[-1].lock_lost
    with pytest.raises(StorageError, match="took this database"):
        place.ready()
