"""Three instances of categorization hand one message on through the feed by
keywords: partner sets a keyword, beleg waits for it and decides the kind,
ablage waits for beleg to be done and moves:
docs/mailbox-agents/concept/categorization-chain.md."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from benethos_mailbox_agents.agents.categorization.agent import Categorization
from benethos_mailbox_agents.records import Decision, Event, MessageRef
from benethos_mailbox_agents.runtime.loop import Worker
from benethos_mailbox_agents.store import Store

from ..agents_fake import ACCOUNT, wire_message
from ..agents_helpers import Wired, mail, settings, wired

QUOTE = "please find attached the invoice for November"

PARTNER: dict[str, Any] = {
    "mark_done": True,
    "dimensions": [
        {
            "name": "partner",
            "categories": [
                {
                    "name": "Hosting",
                    "senders": ["*@hosting.example"],
                    "then": [{"keyword": "agent-partner-hosting"}],
                }
            ],
        }
    ],
}

KINDS = {
    "name": "kind",
    "categories": [
        {
            "name": "Invoice",
            "topic": "Invoices of a provider for a service the owner pays",
            "then": [{"keyword": "agent-invoice"}],
        }
    ],
}

BELEG: dict[str, Any] = {
    "on": {"arrival": "inbox", "keywords": ["agent-partner-*"]},
    "mark_done": True,
    "dimensions": [
        {
            "name": "partner",
            "categories": [
                {"name": "Hosting", "keywords": ["agent-partner-hosting"]},
                {"name": "Telco", "keywords": ["agent-partner-telco"]},
            ],
        },
        KINDS,
    ],
}

ABLAGE: dict[str, Any] = {
    "on": {"keywords": ["agent-categorized-beleg"]},
    "dimensions": [
        {
            "name": "partner",
            "categories": [
                {
                    "name": "Hosting",
                    "keywords": ["agent-partner-hosting"],
                    "then": [{"move": "Invoices/Hosting"}],
                },
                {
                    "name": "Telco",
                    "keywords": ["agent-partner-telco"],
                    "then": [{"move": "Invoices/Telco"}],
                },
            ],
        },
        {
            "name": "kind",
            "categories": [
                {
                    "name": "Invoice",
                    "keywords": ["agent-invoice"],
                    "then": [{"move_below": "Billed"}],
                }
            ],
        },
    ],
}


@dataclass
class Chain:
    world: Wired
    workers: dict[str, Worker]

    async def run(self, name: str) -> None:
        """One pass of the instance ``name``, and the update its writes
        cause in the feed, as the service names it (measured 2026-11-25)."""
        before = json.dumps(mail(self.world, "m1"), sort_keys=True)
        await self.workers[name].run_pass()
        if json.dumps(mail(self.world, "m1"), sort_keys=True) != before:
            self.world.service.change("message.updated", "m1")

    def keywords(self) -> list[str]:
        return sorted(mail(self.world, "m1")["keywords"])


@pytest.fixture
async def chain(tmp_path: Path) -> AsyncIterator[Chain]:
    async with wired(tmp_path) as world:
        with ExitStack() as stack:
            workers: dict[str, Worker] = {}
            for name, listed, stage in (
                ("partner", PARTNER, "keyword"),
                ("beleg", BELEG, "keyword"),
                ("ablage", ABLAGE, "full"),
            ):
                path = tmp_path / f"{name}.json"
                path.write_text(json.dumps(listed), encoding="utf-8")
                agent = Categorization(
                    settings(stage=stage, categorization_file=path, instance=name)
                )
                agent.prepare()
                store = stack.enter_context(Store.open(tmp_path / f"{name}.db"))
                workers[name] = Worker(
                    agent=agent,
                    store=store,
                    mailbox=world.mailbox,
                    gateway=world.gateway,
                    now=world.clock,
                )
                # The first pass starts the feed at now.
                await workers[name].run_pass()
            world.service.add(
                wire_message(
                    "m1",
                    sender="billing@hosting.example",
                    subject="November",
                    text=f"Hello,\n{QUOTE}.\n",
                )
            )
            yield Chain(world, workers)


async def test_the_instances_hand_a_message_on_by_their_keywords(
    chain: Chain,
) -> None:
    chain.world.fake_gateway.answer({"group": "Invoice", "quote": QUOTE})

    await chain.run("partner")
    assert chain.keywords() == ["agent-categorized-partner", "agent-partner-hosting"]
    # ablage waits for beleg: the keyword of partner alone moves nothing.
    await chain.run("ablage")
    assert mail(chain.world, "m1")["folder_ids"] == ["inbox"]

    await chain.run("beleg")
    assert "agent-invoice" in chain.keywords()
    assert "agent-categorized-beleg" in chain.keywords()

    await chain.run("ablage")
    assert mail(chain.world, "m1")["folder_ids"] == ["inv-hosting/Billed"]
    assert "agent-categorized-ablage" in chain.keywords()
    assert len(chain.world.fake_gateway.requests) == 1


async def test_a_change_later_asks_no_model_and_moves_nothing_twice(
    chain: Chain,
) -> None:
    chain.world.fake_gateway.answer({"group": "Invoice", "quote": QUOTE})
    for name in ("partner", "beleg", "ablage"):
        await chain.run(name)
    writes = len(chain.world.service.writes())

    # The update of ablage's move reaches beleg and ablage again.
    for name in ("beleg", "ablage", "beleg", "ablage"):
        await chain.run(name)

    assert len(chain.world.service.writes()) == writes
    assert len(chain.world.fake_gateway.requests) == 1
    moves = [a for a in actions_of(chain, "ablage") if a[0] == "move_to_folder"]
    assert moves == [("move_to_folder", "Invoices/Hosting/Billed", True)]


async def test_a_keyword_corrected_by_hand_reaches_the_code_not_the_model(
    chain: Chain,
) -> None:
    chain.world.fake_gateway.answer({"group": "Invoice", "quote": QUOTE})
    await chain.run("partner")
    await chain.run("beleg")
    # A person corrects the partner of the message.
    found = mail(chain.world, "m1")
    found["keywords"] = [
        "agent-partner-telco" if k == "agent-partner-hosting" else k
        for k in found["keywords"]
    ]
    chain.world.service.change("message.updated", "m1")

    await chain.run("beleg")

    ref = MessageRef(account_id=ACCOUNT, message_id="m1")
    message = await chain.world.mailbox.message(ref)
    decided = chain.workers["beleg"].agent.refresh(
        _stored(chain, "beleg", ref), message
    )
    assert (decided.label, decided.fields) == ("Telco", {"kind": "Invoice"})
    assert len(chain.world.fake_gateway.requests) == 1
    await chain.run("ablage")
    assert mail(chain.world, "m1")["folder_ids"] == ["inv-telco/Billed"]


def test_without_on_keywords_an_update_is_left_as_before(tmp_path: Path) -> None:
    path = tmp_path / "partner.json"
    path.write_text(json.dumps(PARTNER), encoding="utf-8")
    agent = Categorization(settings(categorization_file=path))
    ref = MessageRef(account_id=ACCOUNT, message_id="m1")
    at = datetime(2026, 11, 25, tzinfo=UTC)

    assert agent.select(Event(type="message.updated", ref=ref, at=at)) is None


def actions_of(chain: Chain, name: str) -> list[tuple[str, str, bool]]:
    store = chain.workers[name].store
    ref = MessageRef(account_id=ACCOUNT, message_id="m1")
    return [(a.action, a.argument, a.executed) for a in store.actions(ref)]


def _stored(chain: Chain, name: str, ref: MessageRef) -> Decision:
    steps = [s for s in chain.workers[name].store.steps(ref) if s.step == "decision"]
    return Decision.model_validate(steps[-1].result)
