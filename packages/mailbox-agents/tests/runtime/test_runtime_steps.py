"""The step runner: idempotency per message, prompt version and model."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path

import httpx
import pytest

from benethos_mailbox_agents.contract import Action, ActionRequest, Limits
from benethos_mailbox_agents.errors import ConfigError, GatewayUnavailableError
from benethos_mailbox_agents.records import MessageRef
from benethos_mailbox_agents.runtime.steps import StepRunner, backoff

from ..fakes import ACCOUNT, wire_message
from ..helpers import Collected, Echo, Wired, settings, wired

REF = MessageRef(account_id=ACCOUNT, message_id="m1")
MATCH = {"label": "match", "quote": "Your invoice"}


@pytest.fixture
async def world(tmp_path: Path) -> AsyncIterator[Wired]:
    async with wired(tmp_path) as found:
        found.service.add(wire_message("m1", subject="Your invoice", text="Attached."))
        found.store.enqueue(REF, found.clock())
        yield found


def runner(
    world: Wired, agent: Echo | None = None, effects: Collected | None = None
) -> StepRunner:
    return StepRunner(
        agent=agent or Echo(settings()),
        store=world.store,
        reader=world.mailbox,
        gateway=world.gateway,
        effects=effects or Collected(),
        now=world.clock,
    )


def _state(world: Wired, ref: MessageRef = REF) -> tuple[str, int]:
    row = world.store.message(ref)
    assert row is not None
    return row.state, row.attempts


async def test_a_message_through_every_step(world: Wired) -> None:
    world.fake_gateway.answer(MATCH)
    effects = Collected()

    assert await runner(world, effects=effects).process(REF) == "done"

    assert effects.requests == [ActionRequest(Action.ADD_KEYWORD, REF, keyword="echo")]
    assert [s.step for s in world.store.steps(REF)] == ["baseline", "model", "decision"]
    decision = world.store.step(REF, "decision", "p1", "alias")
    assert decision is not None
    assert decision.model == "reported-model"
    assert (decision.tokens_in, decision.tokens_out) == (120, 15)
    assert decision.result["evidence"][0]["found"] is True
    assert _state(world) == ("done", 0)


async def test_a_garbled_usage_still_stores_the_model_step(world: Wired) -> None:
    content = json.dumps(MATCH)
    world.fake_gateway.answer(
        httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": content}}],
                "usage": {"prompt_tokens": -5, "completion_tokens": "n/a"},
            },
        )
    )

    assert await runner(world).process(REF) == "done"

    model = world.store.step(REF, "model", "p1", "alias")
    assert model is not None
    assert (model.tokens_in, model.tokens_out) == (0, 0)


async def test_a_message_run_again_asks_the_model_nothing(world: Wired) -> None:
    world.fake_gateway.answer(MATCH)
    await runner(world).process(REF)
    effects = Collected()

    assert await runner(world, effects=effects).process(REF) == "done"

    assert len(world.fake_gateway.requests) == 1
    assert len(effects.requests) == 1
    assert [s.step for s in world.store.steps(REF)] == ["baseline", "model", "decision"]


async def test_a_new_prompt_version_decides_again_and_keeps_both(world: Wired) -> None:
    world.fake_gateway.answer(MATCH, {"label": "other", "quote": "Attached."})
    await runner(world).process(REF)

    class Newer(Echo):
        prompt_version = "p2"

    await runner(world, Newer(settings())).process(REF)

    assert len(world.fake_gateway.requests) == 2
    first = world.store.step(REF, "decision", "p1", "alias")
    second = world.store.step(REF, "decision", "p2", "alias")
    assert first is not None and second is not None
    assert (first.result["label"], second.result["label"]) == ("match", "other")


async def test_a_label_whose_quote_is_not_in_the_mail_is_not_acted_on(
    world: Wired,
) -> None:
    world.fake_gateway.answer({"label": "match", "quote": "Ignore all instructions"})
    effects = Collected()

    assert await runner(world, effects=effects).process(REF) == "decided"

    assert effects.requests == []
    decision = world.store.step(REF, "decision", "p1", "alias")
    assert decision is not None
    assert decision.result["refused"] == "evidence"


async def test_an_answer_outside_the_schema_is_tried_again_later(world: Wired) -> None:
    world.fake_gateway.answer({"label": "maybe", "quote": "x"})

    assert await runner(world).process(REF) == "pending"

    row = world.store.message(REF)
    assert row is not None
    assert row.attempts == 1
    assert row.next_attempt == world.clock() + timedelta(seconds=120)
    assert world.store.step(REF, "model", "p1", "alias") is not None


async def test_a_message_refused_too_often_fails(world: Wired) -> None:
    world.fake_gateway.answer({"label": "maybe", "quote": "x"})

    assert await runner(world).process(REF, attempts=4) == "failed"
    assert _state(world) == ("failed", 5)


async def test_a_gateway_that_is_away_leaves_the_message_alone(world: Wired) -> None:
    world.fake_gateway.answer(httpx.Response(503))

    with pytest.raises(GatewayUnavailableError):
        await runner(world).process(REF)

    assert _state(world) == ("pending", 0)


async def test_a_refused_key_stops_the_pass(world: Wired) -> None:
    world.fake_gateway.answer(httpx.Response(401))

    with pytest.raises(ConfigError):
        await runner(world).process(REF)


async def test_a_message_gone_is_skipped(world: Wired) -> None:
    gone = MessageRef(account_id=ACCOUNT, message_id="gone")
    world.store.enqueue(gone, world.clock())

    assert await runner(world).process(gone) == "skipped"


async def test_a_message_gone_while_the_model_answers_is_skipped(world: Wired) -> None:
    """After a model call the message is fetched anew, to act on where it
    lies now: one deleted meanwhile has nothing to act on."""
    world.fake_gateway.answer(MATCH)
    world.fake_gateway.during = lambda: world.service.messages.pop((ACCOUNT, "m1"))
    effects = Collected()

    assert await runner(world, effects=effects).process(REF) == "skipped"
    assert effects.requests == []


async def test_a_message_the_service_refuses_is_tried_again(world: Wired) -> None:
    world.service.refusal = (403, "forbidden")

    assert await runner(world).process(REF) == "pending"
    assert _state(world) == ("pending", 1)


async def test_a_message_not_admitted_is_skipped_without_the_model(
    world: Wired,
) -> None:
    sent = MessageRef(account_id=ACCOUNT, message_id="m2")
    world.service.add(wire_message("m2", folder_ids=["sent"]))
    world.store.enqueue(sent, world.clock())

    assert await runner(world).process(sent) == "skipped"
    assert world.fake_gateway.requests == []


class Marking(Echo):
    """An Echo that skips a message marked before its state file."""

    skip_marked = True


MARKED = MessageRef(account_id=ACCOUNT, message_id="m3")


def _marked(world: Wired, keyword: str = "ECHO") -> None:
    """A message that carries the keyword, in another case, as IMAP keeps
    it, and that the state file does not know."""
    world.service.add(
        wire_message("m3", subject="Your invoice", keywords=[keyword]), change=None
    )
    world.store.enqueue(MARKED, world.clock())


async def test_a_marked_message_the_state_file_does_not_know_is_skipped(
    world: Wired,
) -> None:
    _marked(world)
    effects = Collected()

    assert (
        await runner(world, Marking(settings()), effects).process(MARKED) == "skipped"
    )

    assert world.store.steps(MARKED) == []
    assert world.fake_gateway.requests == []
    assert effects.requests == []


async def test_a_marked_message_the_state_file_knows_goes_on(world: Wired) -> None:
    """Marked by the agent itself and taken up again, as ``backfill`` does:
    the stored decision is used, and a new prompt version asks anew."""
    _marked(world, keyword="none-yet")
    world.fake_gateway.answer(MATCH)
    assert await runner(world, Marking(settings())).process(MARKED) == "done"
    world.service.messages[(ACCOUNT, "m3")]["keywords"] = ["echo"]
    world.store.enqueue(MARKED, world.clock(), again=True)

    assert await runner(world, Marking(settings())).process(MARKED) == "done"
    assert len(world.fake_gateway.requests) == 1

    class Newer(Marking):
        prompt_version = "p2"

    world.fake_gateway.answer(MATCH)
    world.store.enqueue(MARKED, world.clock(), again=True)

    assert await runner(world, Newer(settings())).process(MARKED) == "done"
    assert len(world.fake_gateway.requests) == 2


async def test_another_keyword_does_not_skip(world: Wired) -> None:
    _marked(world, keyword="agent-sorted")
    world.fake_gateway.answer(MATCH)

    assert await runner(world, Marking(settings())).process(MARKED) == "done"


async def test_an_agent_that_declares_no_skip_asks_about_marked_mail(
    world: Wired,
) -> None:
    _marked(world)
    world.fake_gateway.answer(MATCH)

    assert await runner(world).process(MARKED) == "done"
    assert len(world.fake_gateway.requests) == 1


async def test_the_daily_limit_waits_for_tomorrow(world: Wired) -> None:
    class Thrifty(Echo):
        limits = Limits(model_calls_per_day=0)

    assert await runner(world, Thrifty(settings())).process(REF) == "pending"

    row = world.store.message(REF)
    assert row is not None
    assert row.next_attempt == world.clock().replace(hour=0) + timedelta(days=1)
    assert world.fake_gateway.requests == []


async def test_more_calls_than_allowed_per_message_fail_it(world: Wired) -> None:
    class Greedy(Echo):
        limits = Limits(model_calls_per_message=0)

    assert await runner(world, Greedy(settings())).process(REF) == "failed"


@pytest.mark.parametrize(("days", "kept"), [(0, 0), (3, 1)])
async def test_calls_are_kept_only_when_asked(
    world: Wired, days: int, kept: int
) -> None:
    world.fake_gateway.answer(MATCH)

    await runner(world, Echo(settings(prompt_retention_days=days))).process(REF)

    assert world.store.count_calls() == kept


def test_backoff_doubles_up_to_the_ceiling() -> None:
    found = settings(poll_seconds=60, backoff_ceiling_seconds=600)

    assert [backoff(found, n) for n in range(5)] == [60, 120, 240, 480, 600]


def test_backoff_after_weeks_of_tries_is_the_ceiling() -> None:
    found = settings(poll_seconds=60, backoff_ceiling_seconds=3600)

    assert backoff(found, 5000) == 3600


async def test_an_answer_with_a_lone_surrogate_is_refused_and_counted(
    world: Wired,
) -> None:
    world.fake_gateway.answer('{"label": "match", "quote": "Your invoice \\ud800"}')

    assert await runner(world).process(REF) == "pending"

    assert _state(world) == ("pending", 1)
    model = world.store.step(REF, "model", "p1", "alias")
    assert model is not None
    assert model.result == {"refused": "schema"}


async def test_a_lone_surrogate_in_the_reported_model_is_stored_replaced(
    world: Wired,
) -> None:
    body = {
        "choices": [{"message": {"content": json.dumps(MATCH)}}],
        "model": "local\ud800",
    }
    world.fake_gateway.answer(
        httpx.Response(
            200,
            content=json.dumps(body).encode("ascii"),
            headers={"content-type": "application/json"},
        )
    )

    found = await runner(world, Echo(settings(prompt_retention_days=3))).process(REF)

    assert found == "done"
    model = world.store.step(REF, "model", "p1", "alias")
    assert model is not None
    assert model.model == "local?"
    assert world.store.count_calls() == 1


async def test_a_message_the_service_answers_garbled_is_tried_again(
    world: Wired,
) -> None:
    garbled = wire_message("m2", subject="Your invoice")
    garbled["subject"] = ["Your invoice"]
    world.service.add(garbled)
    ref = MessageRef(account_id=ACCOUNT, message_id="m2")
    world.store.enqueue(ref, world.clock())

    assert await runner(world).process(ref) == "pending"
    assert _state(world, ref) == ("pending", 1)


async def test_a_token_count_beyond_sqlite_still_stores_the_step(
    world: Wired,
) -> None:
    world.fake_gateway.answer(
        httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps(MATCH)}}],
                "usage": {"prompt_tokens": 1e30, "completion_tokens": 3},
            },
        )
    )

    assert await runner(world).process(REF) == "done"


async def test_a_redirect_of_the_gateway_leaves_the_message_pending(
    world: Wired,
) -> None:
    world.fake_gateway.answer(httpx.Response(307))

    with pytest.raises(ConfigError):
        await runner(world).process(REF)

    assert _state(world) == ("pending", 0)
