"""The agent categorization choosing a group by its topic, on invented mail and a
gateway of httpx.MockTransport: docs/mailbox-agents/concept/agent-categorization.md."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from benethos_mailbox_agents.agents.categorization.agent import Categorization
from benethos_mailbox_agents.errors import GatewayUnavailableError
from benethos_mailbox_agents.records import MessageRef

from ...agents_fake import ACCOUNT, wire_message
from ...agents_helpers import (
    Wired,
    actions,
    decision,
    mail,
    run,
    settings,
    wired,
    worker,
)

APPLICATIONS = "Applications and CVs of people who want to work with the owner"
NOTES = "Notes the owner sends to himself from the phone"
VAULT = "Statements and letters of a bank about an account of the owner"

GROUPS: list[dict[str, Any]] = [
    {
        "name": "Hosting",
        "folder": "Invoices/Hosting",
        "senders": ["*@hosting.example"],
        "topic": "Mail about the hosting contract",
    },
    {
        "name": "Alpha",
        "folder": "Projects/Alpha",
        "senders": ["*@client.example"],
        "topic": "Mail about the project Alpha: the offer, the weekly status",
        "by_topic": "act",
    },
    {
        "name": "Beta",
        "folder": "Projects/Beta",
        "senders": ["*@client.example"],
        "topic": "Mail about the project Beta: the migration of the shop",
    },
    {
        "name": "Applications",
        "folder": "Applications",
        "topic": APPLICATIONS,
        "by_topic": "act",
    },
    {"name": "Notes", "folder": "Notes", "topic": NOTES},
    {
        "name": "Vault",
        "folder": "Vault",
        "topic": VAULT,
        "by_topic": "act",
        "hold": True,
    },
]

QUOTE = "please find my application for the position attached"
TEXT = f"Hello,\n{QUOTE}, with my CV.\n\nBest regards\n"


def agent(tmp_path: Path, stage: str = "full", groups: Any = None) -> Categorization:
    path = tmp_path / "categorization.json"
    path.write_text(json.dumps({"groups": GROUPS if groups is None else groups}))
    return Categorization(settings(stage=stage, categorization_file=path))


@pytest.fixture
async def topic_world(tmp_path: Path) -> AsyncIterator[Wired]:
    async with wired(tmp_path) as found:
        found.service.add(
            wire_message("hosting", sender="billing@hosting.example"), change=None
        )
        found.service.add(
            wire_message(
                "stranger",
                sender="someone@elsewhere.example",
                subject="Application",
                text=TEXT,
            ),
            change=None,
        )
        found.service.add(
            wire_message(
                "client",
                sender="office@client.example",
                subject="Weekly status of the project Alpha",
                text="Hello,\nhere is the weekly status of the project Alpha.\n",
            ),
            change=None,
        )
        yield found


def said(group: str, quote: str = QUOTE) -> dict[str, str]:
    return {"group": group, "quote": quote}


# -- the sender first ---------------------------------------------------------------


async def test_a_sender_of_one_group_asks_no_model_whatever_its_topic(
    topic_world: Wired, tmp_path: Path
) -> None:
    assert await run(topic_world, "hosting", agent(tmp_path)) == "done"

    assert topic_world.fake_gateway.requests == []
    assert (
        topic_world.store.model_calls_since(topic_world.clock().replace(year=2000)) == 0
    )
    assert mail(topic_world, "hosting")["folder_ids"] == ["inv-hosting"]
    found = decision(topic_world, "hosting")
    assert (found["label"], found["source"]) == ("Hosting", "baseline")


# -- a group by its topic -----------------------------------------------------------


async def test_a_group_that_acts_on_its_topic_is_moved_in_full(
    topic_world: Wired, tmp_path: Path
) -> None:
    topic_world.fake_gateway.answer(said("Applications"))

    assert await run(topic_world, "stranger", agent(tmp_path)) == "done"

    assert mail(topic_world, "stranger")["folder_ids"] == ["Applications"]
    assert mail(topic_world, "stranger")["keywords"] == ["agent-categorized"]
    assert actions(topic_world, "stranger") == [
        ("create_folder", "Applications", True),
        ("move_to_folder", "Applications", True),
        ("add_keyword", "agent-categorized", True),
    ]
    found = decision(topic_world, "stranger")
    assert (found["label"], found["source"]) == ("Applications", "model")
    assert found["details"] == {"match": "topic", "among": "all", "by_topic": "act"}


async def test_in_shadow_a_group_that_acts_on_its_topic_is_recorded(
    topic_world: Wired, tmp_path: Path
) -> None:
    topic_world.fake_gateway.answer(said("Applications"))

    assert await run(topic_world, "stranger", agent(tmp_path, "shadow")) == "done"

    assert topic_world.service.writes() == []
    assert topic_world.service.made() == []
    assert [a[2] for a in actions(topic_world, "stranger")] == [False, False, False]


@pytest.mark.parametrize("by_topic", ["record", None])
async def test_a_group_that_records_its_topic_moves_nothing_in_full(
    topic_world: Wired, tmp_path: Path, by_topic: str | None
) -> None:
    notes = {"name": "Notes", "folder": "Notes", "topic": NOTES}
    if by_topic is not None:
        notes["by_topic"] = by_topic
    topic_world.fake_gateway.answer(said("Notes"))

    found = agent(tmp_path, groups=[notes])
    assert await run(topic_world, "stranger", found) == "done"

    assert topic_world.service.writes() == []
    assert topic_world.service.made() == []
    assert actions(topic_world, "stranger") == [
        ("create_folder", "Notes", False),
        ("move_to_folder", "Notes", False),
        ("add_keyword", "agent-categorized", False),
    ]
    assert decision(topic_world, "stranger")["details"]["by_topic"] == "record"


async def test_a_held_group_that_acts_on_its_topic_moves_nothing(
    topic_world: Wired, tmp_path: Path
) -> None:
    topic_world.fake_gateway.answer(said("Vault"))

    assert await run(topic_world, "stranger", agent(tmp_path)) == "done"

    assert topic_world.service.writes() == []
    assert topic_world.service.made() == []
    assert decision(topic_world, "stranger")["details"]["hold"] == "yes"


# -- the evidence -------------------------------------------------------------------


@pytest.mark.parametrize(
    "quote",
    [
        "the owner wants to hire a new developer for the team",
        APPLICATIONS,  # in the topic, not in the mail
    ],
)
async def test_a_quote_not_in_the_mail_is_not_acted_on(
    topic_world: Wired, tmp_path: Path, quote: str
) -> None:
    topic_world.fake_gateway.answer(said("Applications", quote))

    assert await run(topic_world, "stranger", agent(tmp_path)) == "decided"

    found = decision(topic_world, "stranger")
    assert found["refused"] == "evidence"
    assert actions(topic_world, "stranger") == []
    assert topic_world.service.writes() == []


async def test_none_needs_no_quote_and_does_nothing(
    topic_world: Wired, tmp_path: Path
) -> None:
    topic_world.fake_gateway.answer(said("none", ""))

    assert await run(topic_world, "stranger", agent(tmp_path)) == "done"

    found = decision(topic_world, "stranger")
    assert (found["label"], found["source"], found["refused"]) == (
        "none",
        "model",
        None,
    )
    assert found["details"] == {"match": "none", "among": "all"}
    assert actions(topic_world, "stranger") == []
    assert topic_world.service.writes() == []


# -- what the model is given --------------------------------------------------------


async def test_groups_alike_by_their_sender_are_the_only_choice(
    topic_world: Wired, tmp_path: Path
) -> None:
    topic_world.fake_gateway.answer(
        said("Alpha", "here is the weekly status of the project Alpha")
    )

    assert await run(topic_world, "client", agent(tmp_path)) == "done"

    [body] = topic_world.fake_gateway.bodies()
    schema = body["response_format"]["json_schema"]["schema"]
    assert schema["properties"]["group"]["enum"] == ["Alpha", "Beta", "none"]
    system = body["messages"][0]["content"]
    assert "- Alpha: Mail about the project Alpha" in system
    assert "- Beta: Mail about the project Beta" in system
    for other in ("Hosting", "Applications", "Notes", "Vault"):
        assert f"- {other}:" not in system
    assert mail(topic_world, "client")["folder_ids"] == ["Projects/Alpha"]
    assert decision(topic_world, "client")["details"]["among"] == "senders"


def test_a_list_without_a_topic_asks_no_model(tmp_path: Path) -> None:
    plain = [{"name": "A", "folder": "A", "senders": ["*@a.example"]}]
    found = agent(tmp_path, groups=plain)
    found.prepare()

    assert not found.asks_model()
    with_topic = agent(tmp_path)
    with_topic.prepare()
    assert with_topic.asks_model()


# -- a gateway that is away ---------------------------------------------------------


async def test_a_gateway_away_holds_only_the_mail_that_needs_it(
    topic_world: Wired, tmp_path: Path
) -> None:
    sorter = worker(topic_world, agent(tmp_path))
    for message_id in ("stranger", "hosting"):
        topic_world.store.enqueue(
            MessageRef(account_id=ACCOUNT, message_id=message_id), topic_world.clock()
        )

    await sorter.process_due()

    assert isinstance(sorter.runner.gateway_away, GatewayUnavailableError)

    states = {
        m: topic_world.store.message(MessageRef(account_id=ACCOUNT, message_id=m))
        for m in ("stranger", "hosting")
    }
    assert {m: r.state if r else None for m, r in states.items()} == {
        "stranger": "pending",
        "hosting": "done",
    }
    assert mail(topic_world, "hosting")["folder_ids"] == ["inv-hosting"]
    assert mail(topic_world, "stranger")["folder_ids"] == ["inbox"]


# -- the log ------------------------------------------------------------------------


async def test_no_log_line_names_a_group_or_a_topic(
    topic_world: Wired, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("DEBUG")
    topic_world.fake_gateway.answer(said("Applications"))
    assert await run(topic_world, "stranger", agent(tmp_path, "shadow")) == "done"
    topic_world.fake_gateway.answer(
        said("Beta", "here is the weekly status of the project Alpha")
    )
    assert await run(topic_world, "client", agent(tmp_path)) == "done"

    lines = [r.getMessage() for r in caplog.records]
    for secret in ("Applications", "Alpha", "Beta", APPLICATIONS, QUOTE):
        assert not any(secret in line for line in lines), secret
    moves = [line for line in lines if "move_to_folder" in line]
    assert moves[0].endswith("without carrying it out: topic")
    assert moves[1].endswith("without carrying it out: held")


# -- the report ---------------------------------------------------------------------


def test_the_report_names_a_group_recorded_by_its_topic(tmp_path: Path) -> None:
    from benethos_mailbox_agents.contract import Action, Shown, ShownAction
    from benethos_mailbox_agents.records import Decision

    def chosen(name: str, by_topic: str) -> Decision:
        details = {"match": "topic", "among": "all", "by_topic": by_topic}
        return Decision(label=name, source="model", details=details)

    moved = (ShownAction(Action.MOVE_TO_FOLDER, True),)
    recorded = (ShownAction(Action.MOVE_TO_FOLDER, False),)
    left = Decision(
        label="none", source="model", details={"match": "none", "among": "senders"}
    )
    nowhere = Decision(
        label="none", source="model", details={"match": "none", "among": "all"}
    )

    lines = agent(tmp_path).summarize(
        [
            Shown("a@elsewhere.example", chosen("Applications", "act"), moved),
            Shown("b@elsewhere.example", chosen("Notes", "record"), recorded),
            Shown("c@elsewhere.example", chosen("Notes", "record"), recorded),
            Shown("office@client.example", left),
            Shown("d@elsewhere.example", nowhere),
        ]
    )

    assert lines == [
        "groups:",
        "  Applications: 1 moved",
        "  Notes: 2 recorded by topic",
        "senders in no group, candidates for the list:",
        "  d@elsewhere.example (1 message)",
    ]
