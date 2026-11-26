"""The background loops: a round, then a pause."""

from __future__ import annotations

import logging

import pytest

from benethos_mailbox_service.domain.activity import WORKER, ActivityLog
from benethos_mailbox_service.domain.rounds import rounds
from benethos_mailbox_service.errors import StorageError, StorageUnavailableError


class _StopError(Exception):
    pass


async def test_a_failed_round_is_recorded_and_the_next_one_follows(
    caplog: pytest.LogCaptureFixture,
) -> None:
    done: list[int] = []
    paused: list[float] = []

    async def one() -> None:
        done.append(1)
        if len(done) == 1:
            raise StorageError("the disk is full")

    async def sleep(seconds: float) -> None:
        paused.append(seconds)
        if len(done) == 2:
            raise _StopError

    with pytest.raises(_StopError):
        await rounds(one, pause=5.0, sleep=sleep, activity=ActivityLog(), by=WORKER)
    assert len(done) == 2
    assert paused == [5.0, 5.0]
    assert "the disk is full" in caplog.text


async def test_a_database_away_writes_no_line_a_round_and_sets_the_pause(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The log says it once, elsewhere: a round that meets it is quiet,
    and waits at least as long as the database asks."""
    done: list[int] = []
    paused: list[float] = []

    async def one() -> None:
        done.append(1)
        raise StorageUnavailableError(9 if len(done) < 3 else 2, "AdminShutdown")

    async def sleep(seconds: float) -> None:
        paused.append(seconds)
        if len(done) == 3:
            raise _StopError

    with caplog.at_level(logging.DEBUG), pytest.raises(_StopError):
        await rounds(one, pause=5.0, sleep=sleep, activity=ActivityLog(), by=WORKER)
    assert paused == [9.0, 9.0, 5.0]
    assert "round" not in caplog.text
