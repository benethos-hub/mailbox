"""An actor through the runtime: it waits for a keyword, sees a message
only as Placed, and never asks the model."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import ClassVar

import pytest

from benethos_mailbox_agents.contract import (
    Action,
    ActionRequest,
    Actor,
    Context,
    Limits,
    Placed,
)
from benethos_mailbox_agents.errors import ContractError
from benethos_mailbox_agents.records import Decision, MailMessage, MessageRef
from benethos_mailbox_agents.runtime.loop import Worker

from ..agents_fake import ACCOUNT, wire_message
from ..agents_helpers import Wired, settings, wired


class Marker(Actor):
    """An actor of a test: a message with agent-go gets agent-marked."""

    name = "marker"
    version = "1"
    description = "Marks the mail given agent-go."
    actions = frozenset({Action.ADD_KEYWORD})
    default_keyword = "agent-marked"

    def waits_for(self, keyword: str) -> bool:
        return keyword.casefold() == "agent-go"

    def rule(self, placed: Placed) -> Decision:
        found = any(self.waits_for(k) for k in placed.keywords)
        return Decision(label="rule-1" if found else "none", source="baseline")

    def act(self, decision: Decision, placed: Placed) -> list[ActionRequest]:
        if decision.label == "none":
            return []
        return [ActionRequest(Action.ADD_KEYWORD, placed.ref, keyword=self.keyword)]


def _worker(world: Wired) -> Worker:
    return Worker(
        agent=Marker(settings(stage="full")),
        store=world.store,
        mailbox=world.mailbox,
        gateway=world.gateway,
        now=world.clock,
    )


def _state(world: Wired, message_id: str) -> str | None:
    row = world.store.message(MessageRef(account_id=ACCOUNT, message_id=message_id))
    return None if row is None else row.state


def _keywords(world: Wired, message_id: str) -> list[str]:
    return list(world.service.messages[(ACCOUNT, message_id)]["keywords"])


async def test_a_new_message_waits_for_its_keyword(tmp_path: Path) -> None:
    async with wired(tmp_path) as world:
        worker = _worker(world)
        await worker.run_pass()
        world.service.add(wire_message("m1"))

        await worker.run_pass()
        assert _state(world, "m1") == "skipped"
        assert _keywords(world, "m1") == []

        world.service.messages[(ACCOUNT, "m1")]["keywords"] = ["Agent-Go"]
        world.service.change("message.updated", "m1")
        await worker.run_pass()

        assert _state(world, "m1") == "done"
        assert _keywords(world, "m1") == ["Agent-Go", "agent-marked"]
        assert world.fake_gateway.requests == []


async def test_backfill_takes_up_mail_that_carries_the_keyword(tmp_path: Path) -> None:
    async with wired(tmp_path) as world:
        world.service.add(wire_message("m1", keywords=["agent-go"]), change=None)
        worker = _worker(world)

        assert await worker.backfill(30) == 1
        await worker.process_due()

        assert _state(world, "m1") == "done"
        assert "agent-marked" in _keywords(world, "m1")


@pytest.mark.parametrize("folder", ["trash", "junk", "drafts", "sent"])
async def test_mail_in_a_folder_it_passes_by_is_skipped(
    tmp_path: Path, folder: str
) -> None:
    async with wired(tmp_path) as world:
        worker = _worker(world)
        await worker.run_pass()
        world.service.add(
            wire_message("m1", folder_ids=[folder], keywords=["agent-go"])
        )

        await worker.run_pass()

        assert _state(world, "m1") == "skipped"
        assert world.service.writes() == []


def test_placed_shows_nothing_a_mail_says() -> None:
    names = {f.name for f in dataclasses.fields(Placed)}

    assert names.isdisjoint({"subject", "text", "attachments", "sender", "to", "cc"})


def test_an_actor_asks_no_model() -> None:
    class Asking(Marker):
        limits: ClassVar[Limits] = Limits(model_calls_per_message=1)

    with pytest.raises(ContractError, match="asks no model"):
        Asking.validate_definition()
    assert not Marker(settings()).asks_model()


def test_an_actor_writes_rule_and_act_only() -> None:
    class Reading(Marker):
        async def decide(self, message: MailMessage, context: Context) -> Decision:
            return Decision(label=message.subject or "", source="model")

    with pytest.raises(ContractError, match="not decide"):
        Reading.validate_definition()
