"""The worker loop: feed, tick, cursor last, backoff, pending while away."""

from __future__ import annotations

from datetime import datetime, timedelta

import httpx
import pytest

from benethos_mailbox_agents.contract import (
    Action,
    ActionRequest,
    Context,
    Route,
    Trigger,
)
from benethos_mailbox_agents.errors import MailboxUnavailableError
from benethos_mailbox_agents.records import Event, MailMessage
from benethos_mailbox_agents.runtime.model import Calls

from ..agents_fake import ACCOUNT, wire_message
from ..agents_helpers import Echo, Wired, settings, worker
from .loop_helpers import MATCH, ref, state_of


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

    assert (state_of(world, "m1"), state_of(world, "m2")) == ("done", "done")
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
    assert (state_of(world, "m1"), state_of(world, "m2")) == ("done", "done")
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
    assert state_of(world, "m1") == "pending"
    assert world.store.cursor() == "1"

    world.fake_gateway.answer(MATCH)
    assert await run.run_pass() == 60
    assert state_of(world, "m1") == "done"


async def test_an_expired_cursor_starts_anew_and_backfills(world: Wired) -> None:
    run = worker(world)
    world.service.add(wire_message("m1", subject="Your invoice"), change=None)
    world.store.set_cursor("stale", world.clock())
    world.service.expired.add("stale")
    world.fake_gateway.answer(MATCH)

    await run.run_pass()

    assert world.store.cursor() == "0"
    assert state_of(world, "m1") == "done"


async def test_backfill_again_takes_a_decided_message_up_anew(world: Wired) -> None:
    world.service.add(wire_message("m1", subject="Your invoice"), change=None)
    run = worker(world)
    assert await run.backfill(7) == 1
    world.fake_gateway.answer(MATCH)
    await run.process_due()

    assert await run.backfill(7) == 0
    assert await run.backfill(7, again=True) == 1
    assert state_of(world, "m1") == "pending"


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


async def test_a_folder_renamed_between_two_passes_is_seen_by_its_new_path(
    world: Wired,
) -> None:
    """A renamed folder keeps its id with Microsoft, Gmail and JMAP. Each
    pass reads the folders anew, so a message names the path of now."""
    world.service.add(wire_message("filed", folder_ids=["inv-hosting"]), change=None)
    run = worker(world)
    await run.run_pass()
    before = await world.mailbox.message(ref("filed"))
    for folder in world.service.folders[ACCOUNT]:
        if folder["id"] == "inv-hosting":
            folder["name"] = "Webhosting"

    await run.run_pass()

    after = await world.mailbox.message(ref("filed"))
    assert [f.path for f in before.folders] == ["Invoices/Hosting"]
    assert [f.path for f in after.folders] == ["Invoices/Webhosting"]
