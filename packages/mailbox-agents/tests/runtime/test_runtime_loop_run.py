"""The worker loop running: kept calls purged, until stopped, waits that
stay healthy, the errors that end it and those that do not, and a
service that never answers."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime

import httpx
import pytest

from benethos_mailbox_agents.contract import (
    ActionRequest,
    Context,
    Route,
    Trigger,
)
from benethos_mailbox_agents.errors import MailboxUnavailableError, StateFileError
from benethos_mailbox_agents.records import Event, MailMessage
from benethos_mailbox_agents.runtime.health import check, window
from benethos_mailbox_agents.runtime.loop import Worker
from benethos_mailbox_agents.runtime.steps import backoff

from ..agents_fake import wire_message
from ..agents_helpers import Echo, Wired, settings, worker
from .loop_helpers import MATCH, ref, state_of


async def test_kept_calls_are_purged_after_their_days(world: Wired) -> None:
    run = worker(world, prompt_retention_days=2)
    world.store.add_call(ref("m1"), {}, {}, world.clock())
    world.clock.advance(days=3)

    await run.run_pass()

    assert world.store.count_calls() == 0


async def test_the_loop_runs_until_stopped(world: Wired) -> None:
    run = worker(world, poll_seconds=0.01)
    stop = asyncio.Event()

    async def stopper() -> None:
        while world.store.cursor() is None:
            await asyncio.sleep(0.005)
        world.service.down = True
        await asyncio.sleep(0.05)
        stop.set()

    await asyncio.wait_for(asyncio.gather(run.run(stop), stopper()), timeout=5)

    assert world.store.cursor() == "0"


async def test_a_long_wait_for_the_gateway_stays_healthy(world: Wired) -> None:
    """The loop waits longer than the health window allows, yet stays
    healthy. The gateway answers at once, so its timeout only widens the
    window: the check then has room for a busy test machine, and the fourth
    wait is still longer than the window."""

    def now() -> datetime:
        return datetime.now(UTC)

    agent = Echo(
        settings(
            stage="full",
            poll_seconds=0.05,
            gateway_timeout_seconds=0.45,
            backoff_ceiling_seconds=10,
        )
    )
    assert backoff(agent.settings, 4) > window(agent.settings).total_seconds()
    run = Worker(
        agent=agent,
        store=world.store,
        mailbox=world.mailbox,
        gateway=world.gateway,
        now=now,
    )
    await run.run_pass()
    world.service.add(wire_message("m1", subject="Your invoice"))
    world.fake_gateway.answer(*[httpx.Response(503)] * 50)
    stop = asyncio.Event()
    seen: list[bool] = []

    async def watch() -> None:
        started = time.monotonic()
        while time.monotonic() - started < 2:
            seen.append(check(world.store, agent.settings, now()).healthy)
            await asyncio.sleep(0.01)
        stop.set()

    await asyncio.wait_for(asyncio.gather(run.run(stop), watch()), timeout=10)

    # Four tries: the fourth wait, longer than the window, has begun.
    assert len(world.fake_gateway.requests) >= 4
    assert all(seen)


async def test_a_state_file_error_ends_the_loop(
    world: Wired, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nothing goes on without the state file: the loop does not try the
    same pass forever."""
    run = worker(world, poll_seconds=0.01)

    async def broken() -> float:
        raise StateFileError("the state file x.db: disk I/O error")

    monkeypatch.setattr(run, "run_pass", broken)

    with pytest.raises(StateFileError):
        await asyncio.wait_for(run.run(asyncio.Event()), timeout=5)


async def test_a_config_error_does_not_end_the_loop(world: Wired) -> None:
    run = worker(world, poll_seconds=0.01, backoff_ceiling_seconds=0.02)
    await run.run_pass()
    world.service.add(wire_message("m1", subject="Your invoice"))
    world.fake_gateway.answer(httpx.Response(401), httpx.Response(401), MATCH)
    stop = asyncio.Event()

    async def stopper() -> None:
        while state_of(world, "m1") != "done":
            await asyncio.sleep(0.005)
        stop.set()

    await asyncio.wait_for(asyncio.gather(run.run(stop), stopper()), timeout=5)


@pytest.mark.parametrize(
    ("status", "line", "says"),
    [
        (401, "pass_failed", "failed a pass and waits 0s: ConfigError(config)"),
        (503, "upstream_away", "found an upstream away and waits 0s"),
    ],
)
async def test_a_failed_pass_logs_one_line_with_its_wait(
    world: Wired,
    caplog: pytest.LogCaptureFixture,
    status: int,
    line: str,
    says: str,
) -> None:
    run = worker(world, poll_seconds=0.01, backoff_ceiling_seconds=0.02)
    await run.run_pass()
    world.service.add(wire_message("m1", subject="Your invoice"))
    world.fake_gateway.answer(httpx.Response(status))
    caplog.set_level("WARNING")
    stop = asyncio.Event()

    async def stopper() -> None:
        while not any(".worker." in r.name for r in caplog.records):
            await asyncio.sleep(0.005)
        stop.set()

    await asyncio.wait_for(asyncio.gather(run.run(stop), stopper()), timeout=5)

    lines = [r for r in caplog.records if ".worker." in r.name]
    assert [r.name.rsplit(".", 1)[1] for r in lines] == [line]
    assert says in lines[0].getMessage()


async def test_a_message_the_service_never_answers_holds_up_no_other(
    world: Wired,
) -> None:
    run = worker(world, max_attempts=2)
    await run.run_pass()
    for message_id in ("m1", "m2", "m3"):
        world.service.add(wire_message(message_id, subject="Your invoice"))
    world.service.broken = {"m1"}
    world.fake_gateway.answer(MATCH, MATCH)

    for _ in range(2):
        await run.run_pass()

    assert (state_of(world, "m2"), state_of(world, "m3")) == ("done", "done")
    row = world.store.message(ref("m1"))
    assert row is not None
    assert (row.state, row.attempts) == ("pending", 1)

    world.clock.advance(days=1)
    for _ in range(2):
        await run.run_pass()

    assert state_of(world, "m1") == "failed"


async def test_a_service_that_answers_no_message_leaves_all_pending(
    world: Wired,
) -> None:
    run = worker(world, max_attempts=2)
    await run.run_pass()
    for message_id in ("m1", "m2", "m3"):
        world.service.add(wire_message(message_id, subject="Your invoice"))
    world.service.broken = {"m1", "m2", "m3"}

    for _ in range(6):
        await run.run_pass()

    assert {state_of(world, m) for m in ("m1", "m2", "m3")} == {"pending"}


async def test_an_update_the_service_never_answers_lets_the_cursor_move(
    world: Wired,
) -> None:
    class Watcher(Echo):
        triggers = Trigger(routes={"message.updated": Route.DECIDE})

        def select(self, event: Event) -> Route | None:
            return Route.OBSERVE

        async def observe(
            self, message: MailMessage, context: Context
        ) -> list[ActionRequest]:
            return []

    run = worker(world, Watcher(settings(stage="full", max_attempts=2)))
    await run.run_pass()
    world.service.add(wire_message("m1"), change=None)
    world.service.change("message.updated", "m1")
    world.service.broken = {"m1"}
    cursor = world.store.cursor()

    with pytest.raises(MailboxUnavailableError):
        await run.run_pass()
    assert world.store.cursor() == cursor

    await run.run_pass()

    assert world.store.cursor() != cursor
