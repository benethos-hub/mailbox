"""A classification for a peer: the agent's decision on one message, read
and never acted on, nothing of the mail in what the peer is told."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from benethos_mailbox_agents.contract import Limits
from benethos_mailbox_agents.errors import ContractError
from benethos_mailbox_agents.records import (
    Classified,
    Decision,
    MessageRef,
    NotClassified,
    StepResult,
)
from benethos_mailbox_agents.runtime.classify import Classifier, _ReadItems
from benethos_mailbox_agents.runtime.items import StoredItems

from ..agents_fake import ACCOUNT, wire_message
from ..agents_helpers import Echo, Wired, settings, wired

QUOTE = "the invoice for November"
LONG_AGO = datetime(2000, 1, 1, tzinfo=UTC)


def ref(message_id: str) -> MessageRef:
    return MessageRef(account_id=ACCOUNT, message_id=message_id)


def classifier(world: Wired, agent: Echo | None = None) -> Classifier:
    return Classifier(
        agent or Echo(settings()),
        reader=world.mailbox,
        gateway=world.gateway,
        store=world.store,
        now=world.clock,
    )


async def test_a_message_is_classified_and_nothing_is_written_but_the_call(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    async with wired(tmp_path) as world:
        world.service.add(wire_message("m1", subject="Hi", text=f"Here is {QUOTE}."))
        world.fake_gateway.answer({"label": "match", "quote": QUOTE})
        caplog.set_level("INFO")

        found = await classifier(world).classify(ref("m1"))

        assert found == Classified(
            agent="echo",
            version="p1",
            label="match",
            source="model",
            found={"label": True},
        )
        assert QUOTE not in json.dumps(found.model_dump(mode="json"))
        assert world.store.model_calls_since(LONG_AGO) == 1
        # The call, which the limits of the day count, and no decision.
        assert [s.step for s in world.store.steps(ref("m1"))] == ["model"]
        assert world.store.actions(ref("m1")) == []
        assert world.service.writes() == []
        lines = [r.getMessage() for r in caplog.records]
        assert any("told a peer of message m1: classified" in x for x in lines)
        assert not any(QUOTE in x for x in lines)


async def test_a_label_without_its_quote_is_told_refused(tmp_path: Path) -> None:
    async with wired(tmp_path) as world:
        world.service.add(wire_message("m1", subject="Hi", text="Nothing here."))
        world.fake_gateway.answer({"label": "match", "quote": QUOTE})

        found = await classifier(world).classify(ref("m1"))

    assert isinstance(found, Classified)
    assert found.refused is not None
    assert found.found == {"label": False}


async def test_a_decision_the_worker_stored_is_taken_without_a_call(
    tmp_path: Path,
) -> None:
    async with wired(tmp_path) as world:
        world.service.add(wire_message("m1", subject="Hi", text="Text."))
        stored = Decision(label="other", source="model")
        world.store.add_step(
            ref("m1"),
            StepResult(
                step="decision",
                prompt_version="p1",
                result=stored.model_dump(mode="json"),
                duration_ms=1,
                at=world.clock(),
            ),
            "alias",
        )

        found = await classifier(world).classify(ref("m1"))

        assert isinstance(found, Classified) and found.label == "other"
        assert world.fake_gateway.requests == []


async def test_a_message_gone_is_told_so(tmp_path: Path) -> None:
    async with wired(tmp_path) as world:
        found = await classifier(world).classify(ref("missing"))

    assert found == NotClassified(agent="echo", reason="message_gone")


async def test_the_limits_of_the_day_hold_for_a_peer(tmp_path: Path) -> None:
    class Spare(Echo):
        limits = Limits(model_calls_per_message=1, model_calls_per_day=0)

    async with wired(tmp_path) as world:
        world.service.add(wire_message("m1", subject="Hi", text=f"Here is {QUOTE}."))

        found = await classifier(world, Spare(settings())).classify(ref("m1"))

        assert found == NotClassified(agent="echo", reason="limit_reached")
        assert world.fake_gateway.requests == []


async def test_an_account_outside_the_settings_is_refused_unread(
    tmp_path: Path,
) -> None:
    other = MessageRef(account_id="acc2", message_id="m1")
    async with wired(tmp_path) as world:
        world.service.add(wire_message("m1", account_id="acc2", text=f"{QUOTE}."))
        agent = Echo(settings(accounts=[ACCOUNT]))

        found = await classifier(world, agent).classify(other)

        assert found == NotClassified(agent="echo", reason="message_refused")
        assert not any("/messages/" in r.url.path for r in world.service.requests)
        assert world.fake_gateway.requests == []


async def test_a_message_the_agent_would_not_take_is_refused(tmp_path: Path) -> None:
    async with wired(tmp_path) as world:
        world.service.add(wire_message("m1", folder_ids=["drafts"], text=f"{QUOTE}."))
        world.fake_gateway.answer({"label": "match", "quote": QUOTE})

        found = await classifier(world).classify(ref("m1"))

        assert found == NotClassified(agent="echo", reason="message_refused")
        assert world.fake_gateway.requests == []


async def test_a_classification_opens_closes_and_restarts_no_item(
    tmp_path: Path,
) -> None:
    async with wired(tmp_path) as world:
        items = _ReadItems(StoredItems(world.store, world.clock))
        with pytest.raises(ContractError):
            await items.open(ref("m1"), None, world.clock())
        with pytest.raises(ContractError):
            await items.restart(ref("m1"), world.clock())
        with pytest.raises(ContractError):
            await items.close(ref("m1"), "done")
        assert await items.get(ref("m1")) is None
        assert await items.due(world.clock()) == []
