"""The actor forwarding through the runtime, over the fake service: one
draft per message, by its keywords and its sender check, nothing sent and
no model asked."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from benethos_mailbox_agents.agents.forwarding.agent import Forwarding
from benethos_mailbox_agents.contract import Action, Shown, ShownAction, discover
from benethos_mailbox_agents.errors import ConfigError
from benethos_mailbox_agents.records import Decision
from benethos_mailbox_agents.runtime.readiness import start

from ...agents_fake import wire_message
from ...agents_helpers import Wired, actions, decision, run, settings, wired, worker

INVOICE = "agent-invoice"
TO = "books@example.org"


def agent(tmp_path: Path, stage: str = "suggest", **rule: Any) -> Forwarding:
    path = tmp_path / "forwarding.json"
    found = {"keywords": [INVOICE], "to": [TO], **rule}
    path.write_text(json.dumps({"rules": [found]}), encoding="utf-8")
    return Forwarding(settings(stage=stage, forwarding_file=path))


def drafted(world: Wired) -> list[dict[str, Any]]:
    return [
        json.loads(r.content)
        for r in world.service.requests
        if r.method == "POST" and r.url.path.endswith("/drafts")
    ]


def writes(world: Wired) -> list[str]:
    """Every request that would change the account."""
    return [
        f"{r.method} {r.url.path}" for r in world.service.requests if r.method != "GET"
    ]


def test_the_registry_finds_it() -> None:
    assert discover()["forwarding"] is Forwarding


async def test_in_suggest_one_draft_and_nothing_else(tmp_path: Path) -> None:
    async with wired(tmp_path) as world:
        world.service.add(
            wire_message("m1", keywords=[INVOICE], sender_check="pass"), change=None
        )

        assert await run(world, "m1", agent(tmp_path)) == "done"

        [body] = drafted(world)
        assert body["to"] == [{"email": TO}]
        assert body["reference"] == {"message_id": "m1", "action": "forward"}
        assert len(writes(world)) == 1
        assert world.fake_gateway.requests == []
        assert decision(world, "m1")["label"] == "rule-1"
        assert world.service.messages[("acc1", "m1")]["keywords"] == [INVOICE]


async def test_attachment_is_the_form_asked(tmp_path: Path) -> None:
    async with wired(tmp_path) as world:
        world.service.add(
            wire_message("m1", keywords=[INVOICE], sender_check="pass"), change=None
        )

        await run(world, "m1", agent(tmp_path, forward_as="attachment"))

        [body] = drafted(world)
        assert body["reference"]["forward_as"] == "attachment"


async def test_in_shadow_nothing_is_drafted(tmp_path: Path) -> None:
    async with wired(tmp_path) as world:
        world.service.add(
            wire_message("m1", keywords=[INVOICE], sender_check="pass"), change=None
        )

        assert await run(world, "m1", agent(tmp_path, "shadow")) == "done"

        assert writes(world) == []
        assert actions(world, "m1") == [("draft_forward", f"inline:{TO}", False)]


@pytest.mark.parametrize(
    ("check", "setting", "made"),
    [
        ("pass", "required", True),
        ("unknown", "required", False),
        ("unknown", "off", True),
        ("fail", "off", False),
        ("fail", "required", False),
    ],
)
async def test_the_sender_check_decides_whether_it_is_drafted(
    tmp_path: Path, check: str, setting: str, made: bool
) -> None:
    async with wired(tmp_path) as world:
        world.service.add(
            wire_message("m1", keywords=[INVOICE], sender_check=check), change=None
        )

        await run(world, "m1", agent(tmp_path, sender_check=setting))

        assert bool(drafted(world)) == made
        assert actions(world, "m1") == [("draft_forward", f"inline:{TO}", made)]


async def test_mail_from_a_recipient_is_not_forwarded_back(tmp_path: Path) -> None:
    async with wired(tmp_path) as world:
        world.service.add(
            wire_message(
                "m1",
                keywords=[INVOICE],
                sender="Books@Example.org",
                sender_check="pass",
            ),
            change=None,
        )

        assert await run(world, "m1", agent(tmp_path)) == "done"

        assert writes(world) == []
        assert actions(world, "m1") == []
        assert decision(world, "m1")["details"] == {"why": "from-recipient"}


async def test_a_second_update_drafts_no_second_forward(tmp_path: Path) -> None:
    async with wired(tmp_path) as world:
        running = worker(world, agent(tmp_path))
        await running.run_pass()
        world.service.add(wire_message("m1", keywords=[INVOICE], sender_check="pass"))
        await running.run_pass()
        world.service.messages[("acc1", "m1")]["keywords"] = [INVOICE, "agent-x"]
        world.service.change("message.updated", "m1")
        await running.run_pass()

        assert len(drafted(world)) == 1


async def test_an_account_without_drafts_leaves_the_pass_going(tmp_path: Path) -> None:
    async with wired(tmp_path) as world:
        for message_id in ("m1", "m2"):
            world.service.add(
                wire_message(message_id, keywords=[INVOICE], sender_check="pass"),
                change=None,
            )
        world.service.write_refusal = (501, "not_supported")

        assert await run(world, "m1", agent(tmp_path)) == "done"
        assert await run(world, "m2", agent(tmp_path)) == "done"

        assert world.store.actions() == []


async def test_mail_in_the_trash_is_skipped(tmp_path: Path) -> None:
    async with wired(tmp_path) as world:
        world.service.add(
            wire_message("m1", folder_ids=["trash"], keywords=[INVOICE]), change=None
        )

        assert await run(world, "m1", agent(tmp_path)) == "skipped"
        assert writes(world) == []


def test_its_recipients_are_those_of_its_list(tmp_path: Path) -> None:
    assert agent(tmp_path).recipients() == {TO}


def test_without_its_list_it_does_not_start() -> None:
    with pytest.raises(ConfigError, match="MAILBOX_AGENTS_FORWARDING_FILE"):
        Forwarding(settings()).prepare()


# The settings of the mailbox service, so start() asks for nothing else.
SERVICE = {"service_url": "https://mailbox.example.test", "service_token": "t"}


def test_a_list_that_waits_for_its_own_keyword_does_not_start(
    tmp_path: Path,
) -> None:
    path = tmp_path / "forwarding.json"
    rules = {
        "on": {"keywords": ["agent-*"]},
        "rules": [{"keywords": [INVOICE], "to": [TO]}],
    }
    path.write_text(json.dumps(rules), encoding="utf-8")

    with pytest.raises(ConfigError, match="waits for the agent's own keyword"):
        start(Forwarding, settings(forwarding_file=path, **SERVICE))


def test_the_report_counts_per_rule(tmp_path: Path) -> None:
    def shown(label: str, *done: bool) -> Shown:
        asked = tuple(ShownAction(Action.DRAFT_FORWARD, d) for d in done)
        return Shown(None, Decision(label=label, source="baseline"), asked)

    lines = agent(tmp_path).summarize(
        [shown("rule-1", True), shown("rule-1", False), shown("rule-1"), shown("none")]
    )

    assert lines == ["rules:", "  rule-1: 1 drafted, 1 recorded, 1 left"]
