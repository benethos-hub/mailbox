"""The agent categorization, on invented mail: each row of
docs/mailbox-agents/concept/agent-categorization.md."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from benethos_mailbox_agents.agents.categorization.agent import Categorization
from benethos_mailbox_agents.contract import Action
from benethos_mailbox_agents.errors import MailboxUnavailableError
from benethos_mailbox_agents.records import MessageRef
from benethos_mailbox_agents.runtime.loop import Worker
from benethos_mailbox_agents.runtime.readiness import readiness

from ..agents_fake import ACCOUNT, wire_message
from ..agents_helpers import (
    Wired,
    actions,
    decision,
    mail,
    run,
    settings,
    wired,
    worker,
)

GROUPS: list[dict[str, Any]] = [
    {
        "name": "Bank",
        "folder": "Providers/Bank",
        "senders": ["service@bank-two.example", "*@bank-one.example"],
        "hold": True,
    },
    {
        "name": "CloudHost",
        "folder": "Providers/CloudHost",
        "senders": ["*@cloudhost.example"],
    },
    {"name": "Hosting", "folder": "Invoices/Hosting", "senders": ["*@hosting.example"]},
    {"name": "TelcoA", "folder": "TelcoA", "senders": ["bill*@telco.example"]},
    {"name": "TelcoB", "folder": "TelcoB", "senders": ["*ing@telco.example"]},
]

MESSAGES = {
    "unknown": "someone@elsewhere.example",
    "alike": "billing@telco.example",
    "hosting": "billing@hosting.example",
    "cloudhost": "billing@cloudhost.example",
    "bank": "service@bank-two.example",
}


def listed(tmp_path: Path, groups: list[dict[str, Any]] | None = None) -> Path:
    path = tmp_path / "categorization.json"
    path.write_text(json.dumps({"groups": GROUPS if groups is None else groups}))
    return path


def agent(tmp_path: Path, stage: str = "full", **values: Any) -> Categorization:
    found = {"categorization_file": listed(tmp_path)}
    return Categorization(settings(stage=stage, **{**found, **values}))


@pytest.fixture
async def listed_world(tmp_path: Path) -> AsyncIterator[Wired]:
    async with wired(tmp_path) as found:
        for message_id, sender in MESSAGES.items():
            found.service.add(wire_message(message_id, sender=sender), change=None)
        found.service.add(
            wire_message("filed", sender="billing@hosting.example", folder_ids=["inv"]),
            change=None,
        )
        found.service.add(
            wire_message(
                "binned", sender="billing@hosting.example", folder_ids=["trash"]
            ),
            change=None,
        )
        found.service.add(
            wire_message(
                "put-back",
                sender="billing@hosting.example",
                keywords=["Agent-Categorized"],
            ),
            change=None,
        )
        yield found


# -- section 3: what happens to a message -------------------------------------------


@pytest.mark.parametrize("message_id", ["filed", "binned", "put-back"])
async def test_a_message_not_for_the_agent_is_skipped(
    listed_world: Wired, tmp_path: Path, message_id: str
) -> None:
    before = dict(mail(listed_world, message_id))

    assert await run(listed_world, message_id, agent(tmp_path)) == "skipped"

    assert mail(listed_world, message_id) == before
    assert listed_world.service.writes() == []


async def test_a_sender_in_no_group_is_left_alone(
    listed_world: Wired, tmp_path: Path
) -> None:
    assert await run(listed_world, "unknown", agent(tmp_path)) == "done"

    assert decision(listed_world, "unknown")["label"] == "none"
    assert decision(listed_world, "unknown")["details"] == {"match": "none"}
    assert listed_world.service.writes() == []
    assert listed_world.service.made() == []


async def test_a_sender_of_two_groups_alike_is_left_alone(
    listed_world: Wired, tmp_path: Path
) -> None:
    assert await run(listed_world, "alike", agent(tmp_path)) == "done"

    found = decision(listed_world, "alike")
    assert found["label"] == "none"
    assert found["details"] == {"match": "ambiguous", "groups": "TelcoA,TelcoB"}
    assert listed_world.service.writes() == []


async def test_a_message_of_a_group_is_moved_and_marked(
    listed_world: Wired, tmp_path: Path
) -> None:
    assert await run(listed_world, "hosting", agent(tmp_path)) == "done"

    assert mail(listed_world, "hosting")["folder_ids"] == ["inv-hosting"]
    assert mail(listed_world, "hosting")["keywords"] == ["agent-categorized"]
    assert listed_world.service.made() == []
    found = decision(listed_world, "hosting")
    assert (found["label"], found["source"]) == ("Hosting", "baseline")
    assert found["details"] == {"match": "group", "rule": "pattern"}
    assert "@" not in json.dumps(found)


async def test_a_missing_folder_is_made_from_the_top_first(
    listed_world: Wired, tmp_path: Path
) -> None:
    assert await run(listed_world, "cloudhost", agent(tmp_path)) == "done"

    assert listed_world.service.made() == [
        {"name": "Providers"},
        {"name": "CloudHost", "parent_id": "Providers"},
    ]
    assert mail(listed_world, "cloudhost")["folder_ids"] == ["Providers/CloudHost"]
    assert actions(listed_world, "cloudhost") == [
        ("create_folder", "Providers", True),
        ("create_folder", "Providers/CloudHost", True),
        ("move_to_folder", "Providers/CloudHost", True),
        ("add_keyword", "agent-categorized", True),
    ]


async def test_a_held_group_moves_nothing_in_full(
    listed_world: Wired, tmp_path: Path
) -> None:
    assert await run(listed_world, "bank", agent(tmp_path)) == "done"

    assert listed_world.service.writes() == []
    assert listed_world.service.made() == []
    assert decision(listed_world, "bank")["details"]["hold"] == "yes"
    assert actions(listed_world, "bank") == [
        ("create_folder", "Providers", False),
        ("create_folder", "Providers/Bank", False),
        ("move_to_folder", "Providers/Bank", False),
        ("add_keyword", "agent-categorized", False),
    ]


async def test_a_log_line_names_no_group(
    listed_world: Wired, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("DEBUG")

    assert await run(listed_world, "cloudhost", agent(tmp_path, "shadow")) == "done"
    assert await run(listed_world, "bank", agent(tmp_path, "shadow")) == "done"

    lines = [r.getMessage() for r in caplog.records]
    assert not any("CloudHost" in line or "Bank" in line for line in lines)
    moves = [line for line in lines if "move_to_folder" in line]
    assert moves[0].endswith("without carrying it out: group")
    assert moves[1].endswith("without carrying it out: held")


# -- the stages -----------------------------------------------------------------


@pytest.mark.parametrize("stage", ["shadow", "suggest"])
async def test_below_full_the_folders_and_the_move_are_recorded(
    listed_world: Wired, tmp_path: Path, stage: str
) -> None:
    assert await run(listed_world, "cloudhost", agent(tmp_path, stage)) == "done"

    assert listed_world.service.writes() == []
    assert listed_world.service.made() == []
    assert actions(listed_world, "cloudhost") == [
        ("create_folder", "Providers", False),
        ("create_folder", "Providers/CloudHost", False),
        ("move_to_folder", "Providers/CloudHost", False),
        ("add_keyword", "agent-categorized", False),
    ]


async def test_in_suggest_the_keyword_is_recorded_and_not_set(
    listed_world: Wired, tmp_path: Path
) -> None:
    assert await run(listed_world, "hosting", agent(tmp_path, "suggest")) == "done"

    assert listed_world.service.writes() == []
    assert mail(listed_world, "hosting")["keywords"] == []
    assert actions(listed_world, "hosting") == [
        ("move_to_folder", "Invoices/Hosting", False),
        ("add_keyword", "agent-categorized", False),
    ]


async def test_a_backfill_run_again_records_nothing_twice(
    listed_world: Wired, tmp_path: Path
) -> None:
    for _ in range(3):
        assert await run(
            listed_world, "cloudhost", agent(tmp_path, "shadow"), again=True
        )

    assert actions(listed_world, "cloudhost") == [
        ("create_folder", "Providers", False),
        ("create_folder", "Providers/CloudHost", False),
        ("move_to_folder", "Providers/CloudHost", False),
        ("add_keyword", "agent-categorized", False),
    ]


async def test_below_full_a_folder_that_exists_is_not_recorded(
    listed_world: Wired, tmp_path: Path
) -> None:
    assert await run(listed_world, "hosting", agent(tmp_path, "shadow")) == "done"

    assert actions(listed_world, "hosting") == [
        ("move_to_folder", "Invoices/Hosting", False),
        ("add_keyword", "agent-categorized", False),
    ]


# -- the list as it is when the agent acts --------------------------------------


async def test_a_sender_added_to_the_list_reaches_a_message_decided_before(
    listed_world: Wired, tmp_path: Path
) -> None:
    without = [g for g in GROUPS if g["name"] != "Hosting"]
    first = Categorization(
        settings(stage="full", categorization_file=listed(tmp_path, without))
    )
    assert await run(listed_world, "hosting", first) == "done"
    assert listed_world.service.writes() == []

    assert await run(listed_world, "hosting", agent(tmp_path), again=True) == "done"

    assert mail(listed_world, "hosting")["folder_ids"] == ["inv-hosting"]


async def test_a_changed_list_is_decided_anew(
    listed_world: Wired, tmp_path: Path
) -> None:
    from benethos_mailbox_agents.cli.report import collect, summary

    without = [g for g in GROUPS if g["name"] != "Hosting"]
    first = Categorization(
        settings(stage="full", categorization_file=listed(tmp_path, without))
    )
    first.prepare()
    assert await run(listed_world, "hosting", first) == "done"
    assert decision(listed_world, "hosting")["label"] == "none"

    second = agent(tmp_path)
    second.prepare()
    assert second.prompt_version != first.prompt_version
    assert await run(listed_world, "hosting", second, again=True) == "done"

    found = decision(listed_world, "hosting")
    assert (found["label"], found["details"]) == (
        "Hosting",
        {"match": "group", "rule": "pattern"},
    )
    entries = await collect(listed_world.store, listed_world.mailbox, limit=10)
    assert summary(second, entries) == ["groups:", "  Hosting: 1 moved"]


async def test_the_report_shows_the_baseline_of_the_changed_list(
    listed_world: Wired, tmp_path: Path
) -> None:
    """A backfill under a changed list runs the rules anew beside the
    decision, so the report shows no baseline of the list before."""
    from benethos_mailbox_agents.cli.report import collect, render

    without = [g for g in GROUPS if g["name"] != "Hosting"]
    first = Categorization(
        settings(stage="full", categorization_file=listed(tmp_path, without))
    )
    first.prepare()
    assert await run(listed_world, "hosting", first) == "done"

    second = agent(tmp_path)
    second.prepare()
    backfilling = worker(listed_world, second)
    assert await backfilling.backfill(30, again=True) > 0
    await backfilling.drain()

    entries = await collect(listed_world.store, listed_world.mailbox, limit=20)
    [shown] = [e for e in entries if e.row.ref.message_id == "hosting"]
    lines = render([shown])
    assert any(line.startswith("  decision: Hosting (baseline") for line in lines)
    assert "  baseline: Hosting" in lines


def test_the_version_is_the_list_read(tmp_path: Path) -> None:
    one, other = agent(tmp_path), agent(tmp_path)
    one.prepare()
    other.prepare()

    assert one.prompt_version == other.prompt_version
    assert one.prompt_version.startswith("v1-list-")
    assert len(one.prompt_version) == len("v1-list-") + 12
    assert Categorization.prompt_version == ""

    released = [{**g, "hold": False} for g in GROUPS]
    (tmp_path / "other").mkdir()
    changed = Categorization(
        settings(categorization_file=listed(tmp_path / "other", released))
    )
    changed.prepare()
    assert changed.prompt_version != one.prompt_version


# -- no model -------------------------------------------------------------------


async def test_no_model_is_asked_and_none_counted(
    listed_world: Wired, tmp_path: Path
) -> None:
    worker = Worker(
        agent=agent(tmp_path),
        store=listed_world.store,
        mailbox=listed_world.mailbox,
        gateway=listed_world.gateway,
        now=listed_world.clock,
    )
    for message_id in MESSAGES:
        listed_world.store.enqueue(
            MessageRef(account_id=ACCOUNT, message_id=message_id),
            listed_world.clock(),
        )

    await worker.process_due()

    assert listed_world.fake_gateway.requests == []
    assert listed_world.store.counts()["done"] == len(MESSAGES)


# -- readiness ------------------------------------------------------------------


def test_the_list_is_a_required_setting() -> None:
    found = readiness(
        Categorization, settings(service_url="https://x.test", service_token="t")
    )

    assert found.missing == ("MAILBOX_AGENTS_CATEGORIZATION_FILE",)


def test_a_wrong_list_stops_the_start(tmp_path: Path) -> None:
    path = listed(tmp_path, [{"name": "A", "folder": "A", "senders": ["a.example"]}])
    values = settings(
        service_url="https://x.test", service_token="t", categorization_file=path
    )

    found = readiness(Categorization, values)

    assert found.problem is not None
    assert "group 'A', sender 1 is a domain" in found.problem
    assert "a.example" not in found.problem


# -- the report -----------------------------------------------------------------


def test_summarize_per_group_candidates_and_alike(tmp_path: Path) -> None:
    from benethos_mailbox_agents.contract import Shown, ShownAction
    from benethos_mailbox_agents.records import Decision

    def group(name: str, **details: str) -> Decision:
        return Decision(
            label=name, source="baseline", details={"match": "group", **details}
        )

    none = Decision(label="none", source="baseline", details={"match": "none"})
    alike = Decision(
        label="none",
        source="baseline",
        details={"match": "ambiguous", "groups": "TelcoA,TelcoB"},
    )
    moved = (
        ShownAction(Action.CREATE_FOLDER, True),
        ShownAction(Action.MOVE_TO_FOLDER, True),
    )
    recorded = (ShownAction(Action.MOVE_TO_FOLDER, False),)

    lines = agent(tmp_path).summarize(
        [
            Shown("a@cloudhost.example", group("CloudHost"), moved),
            Shown("b@cloudhost.example", group("CloudHost"), recorded),
            Shown("c@cloudhost.example", group("CloudHost"), ()),
            Shown("s@bank-two.example", group("Bank", hold="yes"), recorded),
            Shown("x@elsewhere.example", none),
            Shown("X@Elsewhere.example", none),
            Shown("y@other.example", none),
            Shown(None, none),
            Shown("billing@telco.example", alike),
        ]
    )

    assert lines == [
        "groups:",
        "  Bank: 1 held",
        "  CloudHost: 1 moved, 1 recorded, 1 not moved",
        "senders in no group, candidates for the list:",
        "  x@elsewhere.example (2 messages)",
        "  y@other.example (1 message)",
        "left alone, two groups name the sender alike:",
        "  billing@telco.example: TelcoA,TelcoB (1 message)",
    ]
    assert agent(tmp_path).summarize([]) == []


async def test_the_report_ends_with_the_groups(
    listed_world: Wired, tmp_path: Path
) -> None:
    from benethos_mailbox_agents.cli.report import collect, render, summary

    for message_id in ("hosting", "unknown"):
        await run(listed_world, message_id, agent(tmp_path))

    entries = await collect(listed_world.store, listed_world.mailbox, limit=10)
    lines = render(entries) + summary(agent(tmp_path), entries)

    assert lines[-4:] == [
        "groups:",
        "  Hosting: 1 moved",
        "senders in no group, candidates for the list:",
        "  someone@elsewhere.example (1 message)",
    ]


async def test_a_keyword_the_service_failed_after_the_move_is_set_again(
    listed_world: Wired, tmp_path: Path
) -> None:
    listed_world.service.keyword_failures = 1
    sorter = worker(listed_world, agent(tmp_path))
    hosting = MessageRef(account_id=ACCOUNT, message_id="hosting")
    listed_world.store.enqueue(hosting, listed_world.clock())

    with pytest.raises(MailboxUnavailableError):
        await sorter.process_due()
    assert mail(listed_world, "hosting")["folder_ids"] == ["inv-hosting"]

    await sorter.process_due()

    row = listed_world.store.message(hosting)
    assert row is not None
    assert row.state == "done"

    assert mail(listed_world, "hosting")["keywords"] == ["agent-categorized"]
    assert mail(listed_world, "hosting")["folder_ids"] == ["inv-hosting"]
