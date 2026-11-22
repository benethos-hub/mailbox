"""The worker loop: feed, tick, cursor last, backoff, pending while away."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from benethos_mailbox_agents.contract import (
    Action,
    ActionRequest,
    Context,
    Route,
    Trigger,
)
from benethos_mailbox_agents.errors import MailboxUnavailableError, StateFileError
from benethos_mailbox_agents.records import Event, MailMessage, MessageRef
from benethos_mailbox_agents.runtime.health import check
from benethos_mailbox_agents.runtime.loop import Worker
from benethos_mailbox_agents.runtime.model import Calls

from ..fakes import ACCOUNT, wire_message
from ..helpers import Echo, Wired, settings, worker

MATCH = {"label": "match", "quote": "Your invoice"}


def ref(message_id: str) -> MessageRef:
    return MessageRef(account_id=ACCOUNT, message_id=message_id)


def _state(world: Wired, message_id: str) -> str:
    row = world.store.message(ref(message_id))
    assert row is not None
    return row.state


async def test_the_first_pass_starts_from_now(world: Wired) -> None:
    world.service.add(wire_message("old", subject="Your invoice"))

    assert await worker(world).run_pass() == 60

    assert world.store.cursor() == "1"
    assert world.store.message(ref("old")) is None
    assert world.store.progress() == world.clock()


async def test_a_new_message_is_decided_and_marked(world: Wired) -> None:
    run = worker(world)
    await run.run_pass()
    world.service.add(wire_message("m1", subject="Your invoice"))
    world.service.add(wire_message("m2", subject="Lunch tomorrow?"))
    world.fake_gateway.answer(MATCH, {"label": "other", "quote": "Lunch tomorrow?"})

    await run.run_pass()

    assert (_state(world, "m1"), _state(world, "m2")) == ("done", "done")
    assert world.service.messages[(ACCOUNT, "m1")]["keywords"] == ["echo"]
    assert world.service.messages[(ACCOUNT, "m2")]["keywords"] == []
    assert world.store.cursor() == "2"


async def test_a_refused_write_blocks_nothing(world: Wired) -> None:
    run = worker(world)
    await run.run_pass()
    world.service.write_refusal = (422, "keyword_refused")
    world.service.add(wire_message("m1", subject="Your invoice"))
    world.service.add(wire_message("m2", subject="Your invoice too"))
    world.fake_gateway.answer(MATCH, MATCH)

    await run.run_pass()

    assert world.store.cursor() == "2"
    assert (_state(world, "m1"), _state(world, "m2")) == ("done", "done")
    assert world.store.actions() == []
    assert world.service.messages[(ACCOUNT, "m1")]["keywords"] == []


async def test_select_sees_only_the_events_of_the_triggers(world: Wired) -> None:
    class Spy(Echo):
        triggers = Trigger(events=frozenset({"message.sent"}))
        seen: list[str] = []

        def select(self, event: Event) -> Route | None:
            self.seen.append(event.type)
            return None

    spy = Spy(settings(stage="full"))
    run = worker(world, spy)
    await run.run_pass()
    world.service.add(wire_message("m1"))
    world.service.add(wire_message("m2"), "message.sent")
    world.service.change("message.updated", "m1")
    world.service.change("mailbox.renamed", "m1")

    await run.run_pass()
    await run.backfill(30)

    assert spy.seen == ["message.sent"]


def test_observe_and_tick_count_into_the_workers_metrics(world: Wired) -> None:
    run = worker(world)

    calls = run.context().model

    assert isinstance(calls, Calls)
    assert calls._metrics is run.metrics


def test_an_agent_reads_the_mailbox_and_cannot_write_it(world: Wired) -> None:
    reader = worker(world).context().reader

    for name in ("move", "add_keyword", "remove_keyword", "folders", "changes"):
        assert not hasattr(reader, name)


async def test_a_repeated_feed_entry_is_harmless(world: Wired) -> None:
    run = worker(world)
    await run.run_pass()
    world.service.add(wire_message("m1", subject="Your invoice"))
    world.service.change("message.created", "m1")
    world.fake_gateway.answer(MATCH)

    await run.run_pass()

    assert len(world.fake_gateway.requests) == 1
    assert len(world.store.actions()) == 1


async def test_the_cursor_moves_last(world: Wired) -> None:
    run = worker(world)
    await run.run_pass()
    world.service.add(wire_message("m1", subject="Your invoice"))
    world.service.down = True

    with pytest.raises(MailboxUnavailableError):
        await run.run_pass()

    assert world.store.cursor() == "0"


async def test_a_message_stays_pending_while_the_gateway_is_away(
    world: Wired,
) -> None:
    run = worker(world)
    await run.run_pass()
    world.service.add(wire_message("m1", subject="Your invoice"))
    world.fake_gateway.answer(httpx.Response(503), httpx.Response(503))

    first = await run.run_pass()
    second = await run.run_pass()

    assert (first, second) == (120, 240)
    assert _state(world, "m1") == "pending"
    assert world.store.cursor() == "1"

    world.fake_gateway.answer(MATCH)
    assert await run.run_pass() == 60
    assert _state(world, "m1") == "done"


async def test_an_expired_cursor_starts_anew_and_backfills(world: Wired) -> None:
    run = worker(world)
    world.service.add(wire_message("m1", subject="Your invoice"), change=None)
    world.store.set_cursor("stale", world.clock())
    world.service.expired.add("stale")
    world.fake_gateway.answer(MATCH)

    await run.run_pass()

    assert world.store.cursor() == "0"
    assert _state(world, "m1") == "done"


async def test_backfill_again_takes_a_decided_message_up_anew(world: Wired) -> None:
    world.service.add(wire_message("m1", subject="Your invoice"), change=None)
    run = worker(world)
    assert await run.backfill(7) == 1
    world.fake_gateway.answer(MATCH)
    await run.process_due()

    assert await run.backfill(7) == 0
    assert await run.backfill(7, again=True) == 1
    assert _state(world, "m1") == "pending"


async def test_backfill_of_an_agent_that_wants_no_folder(world: Wired) -> None:
    """The inbox and sent mail alone: a message in a folder of the owner
    is not taken up by an agent that wants no folder besides."""
    world.service.add(wire_message("in-inbox"), change=None)
    world.service.add(wire_message("filed", folder_ids=["inv-hosting"]), change=None)

    await worker(world).backfill(30)

    pending = {row.ref.message_id for row in world.store.messages("pending", 100)}
    assert "filed" not in pending
    assert "in-inbox" in pending


class Ticking(Echo):
    """Observes updates, and on the tick asks for its keyword on m1."""

    triggers = Trigger(
        events=frozenset({"message.created", "message.updated"}), tick=True
    )
    ticks: list[datetime] = []
    observed: list[str] = []

    def select(self, event: Event) -> Route | None:
        if event.type == "message.updated":
            return Route.OBSERVE
        return super().select(event)

    async def observe(
        self, message: MailMessage, context: Context
    ) -> list[ActionRequest]:
        self.observed.append(message.ref.message_id)
        return []

    async def tick(self, now: datetime, context: Context) -> list[ActionRequest]:
        self.ticks.append(now)
        return [ActionRequest(Action.ADD_KEYWORD, ref("m1"), keyword=self.keyword)]


async def test_the_tick_comes_once_per_interval(world: Wired) -> None:
    world.service.add(wire_message("m1"), change=None)
    agent = Ticking(settings(stage="full", tick_seconds=900))
    agent.ticks = []
    run = worker(world, agent)

    await run.run_pass()
    world.clock.advance(seconds=600)
    await run.run_pass()
    world.clock.advance(seconds=300)
    await run.run_pass()

    assert len(agent.ticks) == 2
    assert world.service.messages[(ACCOUNT, "m1")]["keywords"] == ["echo"]


async def test_after_a_refused_move_on_the_tick_the_rest_is_not_taken(
    world: Wired, caplog: pytest.LogCaptureFixture
) -> None:
    class Moving(Ticking):
        async def tick(self, now: datetime, context: Context) -> list[ActionRequest]:
            return [
                ActionRequest(Action.MOVE_TO_FOLDER, ref("m1"), folder="Nowhere"),
                ActionRequest(Action.ADD_KEYWORD, ref("m1"), keyword=self.keyword),
            ]

    caplog.set_level("INFO")
    world.service.add(wire_message("m1"), change=None)

    await worker(world, Moving(settings(stage="full"))).run_pass()

    assert world.service.writes() == []
    lines = [r.name for r in caplog.records if ".actions." in r.name]
    assert len(lines) == 1 and lines[0].endswith(".refused")


async def test_an_observed_event_is_handed_on_once_per_pass(world: Wired) -> None:
    agent = Ticking(settings(stage="full"))
    agent.observed = []
    run = worker(world, agent)
    await run.run_pass()
    world.service.add(wire_message("m1"), change="message.updated")
    world.service.change("message.updated", "m1")
    world.service.change("message.updated", "gone")

    await run.run_pass()

    assert agent.observed == ["m1"]
    assert world.store.message(ref("m1")) is None


async def test_updates_are_observed_in_the_order_of_the_feed_with_progress(
    world: Wired,
) -> None:
    progress: list[datetime | None] = []

    class Slow(Ticking):
        async def observe(
            self, message: MailMessage, context: Context
        ) -> list[ActionRequest]:
            progress.append(world.store.progress())
            world.clock.advance(minutes=10)
            return await super().observe(message, context)

    agent = Slow(settings(stage="full"))
    agent.observed = []
    run = worker(world, agent)
    await run.run_pass()
    for message_id in ("m2", "m1", "m3"):
        world.service.add(wire_message(message_id), change=None)
    for message_id in ("m2", "m1", "m2", "m3", "m1"):
        world.service.change("message.updated", message_id)
    started = world.clock()

    await run.run_pass()

    assert agent.observed == ["m2", "m1", "m3"]
    assert progress[1:] == [
        started + timedelta(minutes=10),
        started + timedelta(minutes=20),
    ]


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
    def now() -> datetime:
        return datetime.now(UTC)

    agent = Echo(
        settings(
            stage="full",
            poll_seconds=0.05,
            gateway_timeout_seconds=0.05,
            backoff_ceiling_seconds=10,
        )
    )
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
        while time.monotonic() - started < 1.5:
            seen.append(check(world.store, agent.settings, now()).healthy)
            await asyncio.sleep(0.01)
        stop.set()

    await asyncio.wait_for(asyncio.gather(run.run(stop), watch()), timeout=10)

    assert len(world.fake_gateway.requests) >= 3
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
        while _state(world, "m1") != "done":
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

    assert (_state(world, "m2"), _state(world, "m3")) == ("done", "done")
    row = world.store.message(ref("m1"))
    assert row is not None
    assert (row.state, row.attempts) == ("pending", 1)

    world.clock.advance(days=1)
    for _ in range(2):
        await run.run_pass()

    assert _state(world, "m1") == "failed"


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

    assert {_state(world, m) for m in ("m1", "m2", "m3")} == {"pending"}


async def test_an_update_the_service_never_answers_lets_the_cursor_move(
    world: Wired,
) -> None:
    class Watcher(Echo):
        triggers = Trigger(events=frozenset({"message.updated"}))

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
