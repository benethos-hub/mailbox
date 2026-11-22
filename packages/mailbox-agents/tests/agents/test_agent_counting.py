"""The runtime end to end, with the agent that only counts."""

from __future__ import annotations

from pathlib import Path

from benethos_mailbox_agents.agents.counting.agent import Counting
from benethos_mailbox_agents.contract import discover
from benethos_mailbox_agents.records import MessageRef
from benethos_mailbox_agents.runtime.loop import Worker

from ..fakes import ACCOUNT, wire_message
from ..helpers import settings, wired


def test_the_registry_finds_it() -> None:
    assert discover()["counting"] is Counting


async def test_it_counts_every_message_and_changes_none(tmp_path: Path) -> None:
    async with wired(tmp_path) as world:
        worker = Worker(
            agent=Counting(settings(stage="full")),
            store=world.store,
            mailbox=world.mailbox,
            gateway=world.gateway,
            now=world.clock,
        )
        await worker.run_pass()
        world.service.add(wire_message("in1"))
        world.service.add(wire_message("in2"))
        world.service.add(wire_message("out1", folder_ids=["sent"]), "message.sent")
        world.service.add(wire_message("in1"), "message.updated")

        await worker.run_pass()
        await worker.run_pass()

        assert world.store.counts()["done"] == 3
        assert world.fake_gateway.requests == []
        assert world.service.writes() == []
        assert world.store.actions() == []
        sent = world.store.step(
            MessageRef(account_id=ACCOUNT, message_id="out1"), "decision", "", "alias"
        )
        assert sent is not None
        assert sent.result["details"] == {"roles": "sent"}
