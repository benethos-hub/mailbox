"""The outbox while the service's database fails: no job ends as failed
for it. The job stays sending, and is looked into as an unclear one:
found in the sent folder it went out, else it waits again."""

from __future__ import annotations

import asyncio

import pytest

from benethos_mailbox_service.data.models import Message, SentMessage
from benethos_mailbox_service.errors import StorageUnavailableError

from .outbox_helpers import Outbox, Send, build


@pytest.fixture
def box(messages: list[Message]) -> Outbox:
    return build(messages)


def _away() -> StorageUnavailableError:
    return StorageUnavailableError(4, "AdminShutdown (57P01)")


def _sent_then_away(box: Outbox) -> None:
    """The provider sends, then the database fails before it is noted."""
    provider = box.memory()
    real: Send = provider.send

    async def send(raw: bytes, sender: str, recipients: list[str]) -> SentMessage:
        await real(raw, sender, recipients)
        provider.send = real  # type: ignore[method-assign]
        raise _away()

    provider.send = send  # type: ignore[method-assign]


def test_a_database_away_in_the_send_ends_no_job(box: Outbox) -> None:
    box.failing(_away())
    job = box.queue()
    with pytest.raises(StorageUnavailableError):
        box.round()
    assert box.job(job.id).state == "sending"
    asyncio.run(box.runner.recover())
    assert box.job(job.id).state == "queued"


def test_a_job_that_went_out_before_the_database_failed_ends_sent(
    box: Outbox,
) -> None:
    _sent_then_away(box)
    job = box.queue()
    with pytest.raises(StorageUnavailableError):
        box.round()
    assert box.job(job.id).state == "sending"
    asyncio.run(box.runner.recover())
    assert box.job(job.id).state == "sent"
    assert len(box.sent()) == 1


def test_a_database_away_in_the_preparing_ends_no_job(
    box: Outbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = box.queue()
    queued = box.services.mailbox.outgoing.queued

    async def failing(*args: object, **kwargs: object) -> None:
        raise _away()

    monkeypatch.setattr(queued, "prepare", failing)
    with pytest.raises(StorageUnavailableError):
        box.round()
    assert box.job(job.id).state == "sending"


def test_a_job_left_sending_is_looked_into_in_the_next_round(box: Outbox) -> None:
    """No restart: the round after the database came back looks into it."""
    box.failing(_away())
    job = box.queue()
    with pytest.raises(StorageUnavailableError):
        box.round()
    assert box.job(job.id).state == "sending"
    box.round()
    assert box.job(job.id).state == "queued"


async def test_a_database_away_at_the_start_ends_no_runner(box: Outbox) -> None:
    """The first round meets the database away: the runner goes on."""
    jobs = box.services.mailbox.outgoing.outbox.jobs
    real = jobs.open
    calls: list[int] = []

    def failing_once() -> list[object]:
        calls.append(1)
        if len(calls) == 1:
            raise _away()
        return list(real())

    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)
        if len(slept) == 2:
            raise asyncio.CancelledError

    jobs.open = failing_once  # type: ignore[method-assign]
    box.runner._sleep = sleep
    with pytest.raises(asyncio.CancelledError):
        await box.runner.run()
    assert len(calls) >= 2
