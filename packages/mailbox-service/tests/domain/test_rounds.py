"""The background loops: a round, then a pause."""

from __future__ import annotations

import pytest

from benethos_mailbox_service.domain.activity import WORKER, ActivityLog
from benethos_mailbox_service.domain.rounds import rounds
from benethos_mailbox_service.errors import StorageError


class _Stop(Exception):
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
            raise _Stop

    with pytest.raises(_Stop):
        await rounds(one, pause=5.0, sleep=sleep, activity=ActivityLog(), by=WORKER)
    assert len(done) == 2
    assert paused == [5.0, 5.0]
    assert "the disk is full" in caplog.text
