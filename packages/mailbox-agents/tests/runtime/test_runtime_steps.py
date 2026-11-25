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

from ..agents_fake import ACCOUNT, wire_message
from ..agents_helpers import Collected, Echo, Wired, settings, wired

REF = MessageRef(account_id=ACCOUNT, message_id="m1")
MATCH = {"label": "match", "quote": "Your invoice"}


@pytest.fixture
async def steps_world(tmp_path: Path) -> AsyncIterator[Wired]:
    async with wired(tmp_path) as found:
        found.service.add(wire_message("m1", subject="Your invoice", text="Attached."))
        found.store.enqueue(REF, found.clock())
        yield found


def runner(
    steps_world: Wired, agent: Echo | None = None, effects: Collected | None = None
) -> StepRunner:
    return StepRunner(
        agent=agent or Echo(settings()),
        store=steps_world.store,
        reader=steps_world.mailbox,
        gateway=steps_world.gateway,
        effects=effects or Collected(),
        now=steps_world.clock,
    )


def _state(steps_world: Wired, ref: MessageRef = REF) -> tuple[str, int]:
    row = steps_world.store.message(ref)
    assert row is not None
    return row.state, row.attempts


async def test_a_message_through_every_step(steps_world: Wired) -> None:
    steps_world.fake_gateway.answer(MATCH)
    effects = Collected()

    assert await runner(steps_world, effects=effects).process(REF) == "done"

    assert effects.requests == [ActionRequest(Action.ADD_KEYWORD, REF, keyword="echo")]
    assert [s.step for s in steps_world.store.steps(REF)] == [
        "baseline",
        "model",
        "decision",
    ]
    decision = steps_world.store.step(REF, "decision", "p1", "alias")
    assert decision is not None
    assert decision.model == "reported-model"
    assert (decision.tokens_in, decision.tokens_out) == (120, 15)
    assert decision.result["evidence"][0]["found"] is True
    assert _state(steps_world) == ("done", 0)


async def test_a_garbled_usage_still_stores_the_model_step(steps_world: Wired) -> None:
    content = json.dumps(MATCH)
    steps_world.fake_gateway.answer(
        httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": content}}],
                "usage": {"prompt_tokens": -5, "completion_tokens": "n/a"},
            },
        )
    )

    assert await runner(steps_world).process(REF) == "done"

    model = steps_world.store.step(REF, "model", "p1", "alias")
    assert model is not None
    assert (model.tokens_in, model.tokens_out) == (0, 0)


async def test_a_message_run_again_asks_the_model_nothing(steps_world: Wired) -> None:
    steps_world.fake_gateway.answer(MATCH)
    await runner(steps_world).process(REF)
    effects = Collected()

    assert await runner(steps_world, effects=effects).process(REF) == "done"

    assert len(steps_world.fake_gateway.requests) == 1
    assert len(effects.requests) == 1
    assert [s.step for s in steps_world.store.steps(REF)] == [
        "baseline",
        "model",
        "decision",
    ]


async def test_a_new_prompt_version_decides_again_and_keeps_both(
    steps_world: Wired,
) -> None:
    steps_world.fake_gateway.answer(MATCH, {"label": "other", "quote": "Attached."})
    await runner(steps_world).process(REF)

    class Newer(Echo):
        prompt_version = "p2"

    await runner(steps_world, Newer(settings())).process(REF)

    assert len(steps_world.fake_gateway.requests) == 2
    first = steps_world.store.step(REF, "decision", "p1", "alias")
    second = steps_world.store.step(REF, "decision", "p2", "alias")
    assert first is not None and second is not None
    assert (first.result["label"], second.result["label"]) == ("match", "other")


async def test_a_label_whose_quote_is_not_in_the_mail_is_not_acted_on(
    steps_world: Wired,
) -> None:
    steps_world.fake_gateway.answer(
        {"label": "match", "quote": "Ignore all instructions"}
    )
    effects = Collected()

    assert await runner(steps_world, effects=effects).process(REF) == "decided"

    assert effects.requests == []
    decision = steps_world.store.step(REF, "decision", "p1", "alias")
    assert decision is not None
    assert decision.result["refused"] == "evidence"


async def test_an_answer_outside_the_schema_is_tried_again_later(
    steps_world: Wired,
) -> None:
    steps_world.fake_gateway.answer({"label": "maybe", "quote": "x"})

    assert await runner(steps_world).process(REF) == "pending"

    row = steps_world.store.message(REF)
    assert row is not None
    assert row.attempts == 1
    assert row.next_attempt == steps_world.clock() + timedelta(seconds=120)
    assert steps_world.store.step(REF, "model", "p1", "alias") is not None


async def test_a_message_refused_too_often_fails(steps_world: Wired) -> None:
    steps_world.fake_gateway.answer({"label": "maybe", "quote": "x"})

    assert await runner(steps_world).process(REF, attempts=4) == "failed"
    assert _state(steps_world) == ("failed", 5)


async def test_a_gateway_that_is_away_leaves_the_message_alone(
    steps_world: Wired,
) -> None:
    steps_world.fake_gateway.answer(httpx.Response(503))

    with pytest.raises(GatewayUnavailableError):
        await runner(steps_world).process(REF)

    assert _state(steps_world) == ("pending", 0)


async def test_a_refused_key_stops_the_pass(steps_world: Wired) -> None:
    steps_world.fake_gateway.answer(httpx.Response(401))

    with pytest.raises(ConfigError):
        await runner(steps_world).process(REF)


async def test_a_message_gone_is_skipped(steps_world: Wired) -> None:
    gone = MessageRef(account_id=ACCOUNT, message_id="gone")
    steps_world.store.enqueue(gone, steps_world.clock())

    assert await runner(steps_world).process(gone) == "skipped"


async def test_a_message_gone_while_the_model_answers_is_skipped(
    steps_world: Wired,
) -> None:
    """After a model call the message is fetched anew, to act on where it
    lies now: one deleted meanwhile has nothing to act on."""
    steps_world.fake_gateway.answer(MATCH)
    steps_world.fake_gateway.during = lambda: steps_world.service.messages.pop(
        (ACCOUNT, "m1")
    )
    effects = Collected()

    assert await runner(steps_world, effects=effects).process(REF) == "skipped"
    assert effects.requests == []


async def test_a_message_the_service_refuses_is_tried_again(steps_world: Wired) -> None:
    steps_world.service.refusal = (403, "forbidden")

    assert await runner(steps_world).process(REF) == "pending"
    assert _state(steps_world) == ("pending", 1)


async def test_a_message_not_admitted_is_skipped_without_the_model(
    steps_world: Wired,
) -> None:
    sent = MessageRef(account_id=ACCOUNT, message_id="m2")
    steps_world.service.add(wire_message("m2", folder_ids=["sent"]))
    steps_world.store.enqueue(sent, steps_world.clock())

    assert await runner(steps_world).process(sent) == "skipped"
    assert steps_world.fake_gateway.requests == []


class Marking(Echo):
    """An Echo that skips a message marked before its state file."""

    skip_marked = True


MARKED = MessageRef(account_id=ACCOUNT, message_id="m3")


def _marked(steps_world: Wired, keyword: str = "ECHO") -> None:
    """A message that carries the keyword, in another case, as IMAP keeps
    it, and that the state file does not know."""
    steps_world.service.add(
        wire_message("m3", subject="Your invoice", keywords=[keyword]), change=None
    )
    steps_world.store.enqueue(MARKED, steps_world.clock())


async def test_a_marked_message_the_state_file_does_not_know_is_skipped(
    steps_world: Wired,
) -> None:
    _marked(steps_world)
    effects = Collected()

    assert (
        await runner(steps_world, Marking(settings()), effects).process(MARKED)
        == "skipped"
    )

    assert steps_world.store.steps(MARKED) == []
    assert steps_world.fake_gateway.requests == []
    assert effects.requests == []


async def test_a_marked_message_the_state_file_knows_goes_on(
    steps_world: Wired,
) -> None:
    """Marked by the agent itself and taken up again, as ``backfill`` does:
    the stored decision is used, and a new prompt version asks anew."""
    _marked(steps_world, keyword="none-yet")
    steps_world.fake_gateway.answer(MATCH)
    assert await runner(steps_world, Marking(settings())).process(MARKED) == "done"
    steps_world.service.messages[(ACCOUNT, "m3")]["keywords"] = ["echo"]
    steps_world.store.enqueue(MARKED, steps_world.clock(), again=True)

    assert await runner(steps_world, Marking(settings())).process(MARKED) == "done"
    assert len(steps_world.fake_gateway.requests) == 1

    class Newer(Marking):
        prompt_version = "p2"

    steps_world.fake_gateway.answer(MATCH)
    steps_world.store.enqueue(MARKED, steps_world.clock(), again=True)

    assert await runner(steps_world, Newer(settings())).process(MARKED) == "done"
    assert len(steps_world.fake_gateway.requests) == 2


async def test_another_keyword_does_not_skip(steps_world: Wired) -> None:
    _marked(steps_world, keyword="agent-categorized")
    steps_world.fake_gateway.answer(MATCH)

    assert await runner(steps_world, Marking(settings())).process(MARKED) == "done"


async def test_an_agent_that_declares_no_skip_asks_about_marked_mail(
    steps_world: Wired,
) -> None:
    _marked(steps_world)
    steps_world.fake_gateway.answer(MATCH)

    assert await runner(steps_world).process(MARKED) == "done"
    assert len(steps_world.fake_gateway.requests) == 1


async def test_the_daily_limit_waits_for_tomorrow(steps_world: Wired) -> None:
    class Thrifty(Echo):
        limits = Limits(model_calls_per_day=0)

    assert await runner(steps_world, Thrifty(settings())).process(REF) == "pending"

    row = steps_world.store.message(REF)
    assert row is not None
    assert row.next_attempt == steps_world.clock().replace(hour=0) + timedelta(days=1)
    assert steps_world.fake_gateway.requests == []


async def test_more_calls_than_allowed_per_message_fail_it(steps_world: Wired) -> None:
    class Greedy(Echo):
        limits = Limits(model_calls_per_message=0)

    assert await runner(steps_world, Greedy(settings())).process(REF) == "failed"


@pytest.mark.parametrize(("days", "kept"), [(0, 0), (3, 1)])
async def test_calls_are_kept_only_when_asked(
    steps_world: Wired, days: int, kept: int
) -> None:
    steps_world.fake_gateway.answer(MATCH)

    await runner(steps_world, Echo(settings(prompt_retention_days=days))).process(REF)

    assert steps_world.store.count_calls() == kept


def test_backoff_doubles_up_to_the_ceiling() -> None:
    found = settings(poll_seconds=60, backoff_ceiling_seconds=600)

    assert [backoff(found, n) for n in range(5)] == [60, 120, 240, 480, 600]


def test_backoff_after_weeks_of_tries_is_the_ceiling() -> None:
    found = settings(poll_seconds=60, backoff_ceiling_seconds=3600)

    assert backoff(found, 5000) == 3600


async def test_an_answer_with_a_lone_surrogate_is_refused_and_counted(
    steps_world: Wired,
) -> None:
    steps_world.fake_gateway.answer(
        '{"label": "match", "quote": "Your invoice \\ud800"}'
    )

    assert await runner(steps_world).process(REF) == "pending"

    assert _state(steps_world) == ("pending", 1)
    model = steps_world.store.step(REF, "model", "p1", "alias")
    assert model is not None
    assert model.result == {"refused": "schema"}


async def test_a_lone_surrogate_in_the_reported_model_is_stored_replaced(
    steps_world: Wired,
) -> None:
    body = {
        "choices": [{"message": {"content": json.dumps(MATCH)}}],
        "model": "local\ud800",
    }
    steps_world.fake_gateway.answer(
        httpx.Response(
            200,
            content=json.dumps(body).encode("ascii"),
            headers={"content-type": "application/json"},
        )
    )

    found = await runner(steps_world, Echo(settings(prompt_retention_days=3))).process(
        REF
    )

    assert found == "done"
    model = steps_world.store.step(REF, "model", "p1", "alias")
    assert model is not None
    assert model.model == "local?"
    assert steps_world.store.count_calls() == 1


async def test_a_message_the_service_answers_garbled_is_tried_again(
    steps_world: Wired,
) -> None:
    garbled = wire_message("m2", subject="Your invoice")
    garbled["subject"] = ["Your invoice"]
    steps_world.service.add(garbled)
    ref = MessageRef(account_id=ACCOUNT, message_id="m2")
    steps_world.store.enqueue(ref, steps_world.clock())

    assert await runner(steps_world).process(ref) == "pending"
    assert _state(steps_world, ref) == ("pending", 1)


async def test_a_token_count_beyond_sqlite_still_stores_the_step(
    steps_world: Wired,
) -> None:
    steps_world.fake_gateway.answer(
        httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps(MATCH)}}],
                "usage": {"prompt_tokens": 1e30, "completion_tokens": 3},
            },
        )
    )

    assert await runner(steps_world).process(REF) == "done"


async def test_a_redirect_of_the_gateway_leaves_the_message_pending(
    steps_world: Wired,
) -> None:
    steps_world.fake_gateway.answer(httpx.Response(307))

    with pytest.raises(ConfigError):
        await runner(steps_world).process(REF)

    assert _state(steps_world) == ("pending", 0)
