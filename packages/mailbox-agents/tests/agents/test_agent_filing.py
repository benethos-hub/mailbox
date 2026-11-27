"""The actor filing through the runtime, over the fake service: it files
mail by its keywords, once, and asks no model."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from benethos_mailbox_agents.agents.filing.agent import Filing
from benethos_mailbox_agents.contract import discover
from benethos_mailbox_agents.errors import ConfigError, MailboxUnavailableError
from benethos_mailbox_agents.records import MessageRef

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

PARTNER = "agent-partner-cloudhost"
INVOICE = "agent-invoice"
RULES: dict[str, Any] = {
    "rules": [
        {"keywords": [PARTNER], "move": "Providers/CloudHost"},
        {"keywords": [INVOICE], "below": "Invoices"},
    ]
}
TARGET = "Providers/CloudHost/Invoices"


def agent(tmp_path: Path, stage: str = "full", rules: Any = None) -> Filing:
    path = tmp_path / "filing.json"
    path.write_text(json.dumps(RULES if rules is None else rules), encoding="utf-8")
    return Filing(settings(stage=stage, filing_file=path))


def _folder_of(world: Wired, message_id: str) -> list[str]:
    paths = {f["id"]: f for f in world.service.folders[ACCOUNT]}
    found = []
    for folder_id in mail(world, message_id)["folder_ids"]:
        names = []
        folder: dict[str, Any] | None = paths[folder_id]
        while folder is not None:
            names.append(folder["name"])
            parent = folder.get("parent_id")
            folder = paths[parent] if parent else None
        found.append("/".join(reversed(names)))
    return found


def test_the_registry_finds_it() -> None:
    assert discover()["filing"] is Filing


async def test_in_full_it_makes_the_folders_moves_once_and_marks(
    tmp_path: Path,
) -> None:
    async with wired(tmp_path) as world:
        world.service.add(wire_message("m1", keywords=[PARTNER, INVOICE]), change=None)

        assert await run(world, "m1", agent(tmp_path)) == "done"

        assert [f["name"] for f in world.service.made()] == [
            "Providers",
            "CloudHost",
            "Invoices",
        ]
        assert _folder_of(world, "m1") == [TARGET]
        assert mail(world, "m1")["keywords"] == [PARTNER, INVOICE, "agent-filed"]
        assert decision(world, "m1")["label"] == "rule-1"
        assert decision(world, "m1")["details"] == {"move": "1", "below": "2"}
        assert world.fake_gateway.requests == []
        moves = [a for a in actions(world, "m1") if a[0] == "move_to_folder"]
        assert moves == [("move_to_folder", TARGET, True)]


@pytest.mark.parametrize("stage", ["shadow", "suggest"])
async def test_below_full_the_move_is_recorded_and_nothing_written(
    tmp_path: Path, stage: str
) -> None:
    async with wired(tmp_path) as world:
        world.service.add(wire_message("m1", keywords=[PARTNER, INVOICE]), change=None)

        assert await run(world, "m1", agent(tmp_path, stage)) == "done"

        assert world.service.writes() == []
        assert world.service.made() == []
        assert ("move_to_folder", TARGET, False) in actions(world, "m1")
        assert ("add_keyword", "agent-filed", False) in actions(world, "m1")


async def test_a_message_given_the_keyword_later_is_filed(tmp_path: Path) -> None:
    async with wired(tmp_path) as world:
        running = worker(world, agent(tmp_path))
        await running.run_pass()
        world.service.add(wire_message("m1"))
        await running.run_pass()
        assert _folder_of(world, "m1") == ["INBOX"]

        mail(world, "m1")["keywords"] = [PARTNER]
        world.service.change("message.updated", "m1")
        await running.run_pass()

        assert _folder_of(world, "m1") == ["Providers/CloudHost"]
        assert "agent-filed" in mail(world, "m1")["keywords"]


@pytest.mark.parametrize("unmark", [False, True])
async def test_a_message_put_back_by_hand_stays_where_it_was_put(
    tmp_path: Path, unmark: bool
) -> None:
    async with wired(tmp_path) as world:
        running = worker(world, agent(tmp_path))
        await running.run_pass()
        world.service.add(wire_message("m1", keywords=[PARTNER]))
        await running.run_pass()
        assert _folder_of(world, "m1") == ["Providers/CloudHost"]

        mail(world, "m1")["folder_ids"] = ["inbox"]
        kept = [] if unmark else ["agent-filed"]
        mail(world, "m1")["keywords"] = [PARTNER, INVOICE, *kept]
        world.service.change("message.updated", "m1")
        await running.run_pass()

        assert _folder_of(world, "m1") == ["INBOX"]
        moves = [a for a in actions(world, "m1") if a[0] == "move_to_folder"]
        assert [m for m in moves if m[2]] == [
            ("move_to_folder", "Providers/CloudHost", True)
        ]


async def test_below_the_folder_of_the_owner_it_lies_in(tmp_path: Path) -> None:
    async with wired(tmp_path) as world:
        world.service.add(
            wire_message("m1", folder_ids=["inv-telco"], keywords=[INVOICE]),
            change=None,
        )

        assert await run(world, "m1", agent(tmp_path)) == "done"

        assert [f["name"] for f in world.service.made()] == ["Invoices"]
        assert _folder_of(world, "m1") == ["Invoices/Telco/Invoices"]


async def test_a_below_of_two_names_is_made_under_the_owner_s_folder(
    tmp_path: Path,
) -> None:
    rules = {"rules": [{"keywords": [INVOICE], "below": "Archive/2026"}]}
    async with wired(tmp_path) as world:
        world.service.add(
            wire_message("m1", folder_ids=["inv-telco"], keywords=[INVOICE]),
            change=None,
        )

        assert await run(world, "m1", agent(tmp_path, rules=rules)) == "done"

        assert [f["name"] for f in world.service.made()] == ["Archive", "2026"]
        assert _folder_of(world, "m1") == ["Invoices/Telco/Archive/2026"]
        assert "agent-filed" in mail(world, "m1")["keywords"]


async def test_a_keyword_the_service_failed_after_the_move_is_set_again(
    tmp_path: Path,
) -> None:
    rules = {"rules": [{"keywords": [INVOICE], "move": "Invoices"}]}
    async with wired(tmp_path) as world:
        world.service.add(wire_message("m1", keywords=[INVOICE]), change=None)
        world.service.keyword_failures = 1
        filer = worker(world, agent(tmp_path, rules=rules))
        world.store.enqueue(
            MessageRef(account_id=ACCOUNT, message_id="m1"), world.clock()
        )

        with pytest.raises(MailboxUnavailableError):
            await filer.process_due()
        assert _folder_of(world, "m1") == ["Invoices"]

        await filer.process_due()

        assert mail(world, "m1")["keywords"] == [INVOICE, "agent-filed"]
        assert _folder_of(world, "m1") == ["Invoices"]


@pytest.mark.parametrize(
    ("folder", "keywords"),
    [
        ("inbox", [PARTNER, "agent-filed"]),
        ("trash", [PARTNER]),
        ("sent", [PARTNER]),
        ("drafts", [PARTNER]),
    ],
)
async def test_mail_it_does_not_take_is_skipped(
    tmp_path: Path, folder: str, keywords: list[str]
) -> None:
    async with wired(tmp_path) as world:
        world.service.add(
            wire_message("m1", folder_ids=[folder], keywords=keywords), change=None
        )

        assert await run(world, "m1", agent(tmp_path)) == "skipped"
        assert world.service.writes() == []


async def test_an_account_that_cannot_do_it_leaves_the_pass_going(
    tmp_path: Path,
) -> None:
    """Each write answers 501 not_supported: every message ends, refused,
    and none waits for a service that is there."""
    async with wired(tmp_path) as world:
        for message_id in ("m1", "m2"):
            world.service.add(wire_message(message_id, keywords=[PARTNER]), change=None)
        world.service.write_refusal = (501, "not_supported")

        assert await run(world, "m1", agent(tmp_path)) == "done"
        assert await run(world, "m2", agent(tmp_path)) == "done"

        assert world.store.actions() == []


def test_a_list_that_waits_for_its_own_keyword_is_refused(tmp_path: Path) -> None:
    rules = {"on": {"keywords": ["agent-*"]}, "rules": RULES["rules"]}

    with pytest.raises(ConfigError, match="agent.s own keyword"):
        agent(tmp_path, rules=rules).prepare()


def test_without_its_list_it_does_not_start(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="MAILBOX_AGENTS_FILING_FILE"):
        Filing(settings()).prepare()


def test_the_report_counts_per_rule(tmp_path: Path) -> None:
    from benethos_mailbox_agents.contract import Action, Shown, ShownAction
    from benethos_mailbox_agents.records import Decision

    def shown(label: str, *done: bool) -> Shown:
        moves = tuple(ShownAction(Action.MOVE_TO_FOLDER, d) for d in done)
        return Shown(None, Decision(label=label, source="baseline"), moves)

    lines = agent(tmp_path).summarize(
        [shown("rule-2", True), shown("rule-1", False), shown("rule-1"), shown("none")]
    )

    assert lines == ["rules:", "  rule-1: 1 recorded, 1 left", "  rule-2: 1 moved"]
    assert ACCOUNT not in "".join(lines)
