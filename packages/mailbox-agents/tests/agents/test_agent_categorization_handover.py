"""Instances of categorization that hand a message on by keywords: the
recognizer keyword, the sign of an instance that is done, and an
instance that waits for a keyword:
docs/mailbox-agents/concept/categorization-chain.md."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from benethos_mailbox_agents.agents.categorization.agent import Categorization
from benethos_mailbox_agents.cli import main
from benethos_mailbox_agents.errors import ConfigError
from benethos_mailbox_agents.runtime.readiness import start

from ..agents_helpers import settings
from .categorization_chain_helpers import (
    Scripted,
    categorization,
    context,
    decided,
    message,
)


def plain(requests: list[Any]) -> list[tuple[str, str, bool]]:
    return [(r.action.value, r.folder or r.keyword or "", r.held) for r in requests]


def kinds(**extra: Any) -> dict[str, Any]:
    """A list that reads the keywords an earlier instance set."""
    return {
        **extra,
        "dimensions": [
            {
                "name": "partner",
                "categories": [
                    {"name": "Bank", "keywords": ["agent-partner-bank"]},
                    {
                        "name": "Bank invoice",
                        "keywords": ["agent-partner-bank", "agent-invoice"],
                        "then": [{"move": "Providers/Bank/Invoices"}],
                    },
                    {"name": "Telco", "keywords": ["agent-partner-telco"]},
                ],
            }
        ],
    }


@pytest.mark.parametrize(
    ("keywords", "label", "match"),
    [
        (["agent-partner-bank"], "Bank", "keyword"),
        (["Agent-Partner-Bank", "agent-invoice"], "Bank invoice", "keyword"),
        (["agent-invoice"], "none", "none"),
        ([], "none", "none"),
        (["agent-partner-bank", "agent-partner-telco"], "none", "ambiguous"),
    ],
)
async def test_the_recognizer_keyword_reads_the_keywords_a_message_carries(
    tmp_path: Path, keywords: list[str], label: str, match: str
) -> None:
    model = Scripted()

    found = await decided(
        categorization(tmp_path, kinds()),
        message("a@x.example", keywords=keywords),
        model,
    )

    assert (found.label, found.details["match"], found.source) == (
        label,
        match,
        "baseline",
    )
    assert model.asked == []


def test_a_list_of_keywords_alone_asks_no_model(tmp_path: Path) -> None:
    assert not categorization(tmp_path, kinds()).asks_model()


async def test_with_mark_done_the_sign_is_set_also_for_none(tmp_path: Path) -> None:
    agent = categorization(tmp_path, kinds(mark_done=True))
    found = message("a@x.example")
    decision = await decided(agent, found, Scripted())

    requests = await agent.effect(decision, found, context(Scripted()))

    assert decision.label == "none"
    assert plain(requests) == [("add_keyword", "agent-categorized", False)]


async def test_with_mark_done_the_sign_comes_before_the_move(tmp_path: Path) -> None:
    agent = categorization(tmp_path, kinds(mark_done=True))
    found = message("a@x.example", keywords=["agent-partner-bank", "agent-invoice"])
    decision = await decided(agent, found, Scripted())

    requests = await agent.effect(decision, found, context(Scripted()))

    assert plain(requests)[0] == ("add_keyword", "agent-categorized", False)
    assert plain(requests)[-1] == (
        "move_to_folder",
        "Providers/Bank/Invoices",
        False,
    )


async def test_without_mark_done_the_sign_comes_with_a_move_alone(
    tmp_path: Path,
) -> None:
    agent = categorization(tmp_path, kinds())
    for keywords, signed in (
        (["agent-partner-bank"], False),
        (["agent-partner-bank", "agent-invoice"], True),
    ):
        found = message("a@x.example", keywords=keywords)
        decision = await decided(agent, found, Scripted())

        requests = await agent.effect(decision, found, context(Scripted()))

        assert (
            ("add_keyword", "agent-categorized", False) in plain(requests)
        ) is signed


# -- finding 16: no circles --------------------------------------------------------


def circle_lists(tmp_path: Path, closed: bool) -> list[str]:
    """A sets agent-x and waits for agent-y, B sets agent-y and waits for
    agent-x when ``closed``, for agent-z when not."""
    found = []
    for name, sets, waits in (
        ("a", "agent-x", "agent-y"),
        ("b", "agent-y", "agent-x" if closed else "agent-z"),
    ):
        listed = {
            "on": {"keywords": [waits]},
            "dimensions": [
                {
                    "name": "kind",
                    "categories": [
                        {
                            "name": "Any",
                            "keywords": [waits],
                            "then": [{"keyword": sets}],
                        }
                    ],
                }
            ],
        }
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(listed), encoding="utf-8")
        found.append(f"{name}={path}")
    return found


@pytest.mark.parametrize(("closed", "code"), [(True, 1), (False, 0)])
def test_the_command_check_finds_a_circle_of_lists(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], closed: bool, code: int
) -> None:
    lists = circle_lists(tmp_path, closed)

    assert main(["check", "--agent", "categorization", *lists]) == code

    out = capsys.readouterr().out
    if closed:
        assert "categorization: a circle: a -> b -> a" in out
        assert out.count("a circle") == 1
    else:
        assert "categorization: 2 lists, no problem found" in out


def test_the_sign_of_an_instance_closes_a_circle_too(tmp_path: Path) -> None:
    waits_for_b = {
        "on": {"keywords": ["agent-categorized-b"]},
        "mark_done": True,
        "dimensions": [
            {"name": "kind", "categories": [{"name": "Any", "keywords": ["agent-q"]}]}
        ],
    }
    waits_for_a = {**waits_for_b, "on": {"keywords": ["agent-categorized-a"]}}
    paths = {}
    for name, listed in (("a", waits_for_b), ("b", waits_for_a)):
        paths[name] = tmp_path / f"{name}.json"
        paths[name].write_text(json.dumps(listed), encoding="utf-8")

    assert Categorization.check_together(paths) == ["a circle: a -> b -> a"]


def test_the_sign_of_a_list_that_moves_below_alone_closes_a_circle(
    tmp_path: Path,
) -> None:
    below = [{"move_below": "Invoices"}]
    category = {"name": "Any", "keywords": ["agent-q"], "then": below}
    waits_for_b = {
        "on": {"keywords": ["agent-categorized-b"]},
        "dimensions": [{"name": "kind", "categories": [category]}],
    }
    waits_for_a = {**waits_for_b, "on": {"keywords": ["agent-categorized-a"]}}
    paths = {}
    for name, listed in (("a", waits_for_b), ("b", waits_for_a)):
        paths[name] = tmp_path / f"{name}.json"
        paths[name].write_text(json.dumps(listed), encoding="utf-8")

    assert Categorization.check_together(paths) == ["a circle: a -> b -> a"]


def test_a_list_waiting_for_its_own_keyword_does_not_start(tmp_path: Path) -> None:
    listed = {
        "on": {"keywords": ["agent-categorized-*"]},
        "dimensions": [
            {"name": "kind", "categories": [{"name": "Any", "keywords": ["agent-q"]}]}
        ],
    }
    path = tmp_path / "self.json"
    path.write_text(json.dumps(listed), encoding="utf-8")

    with pytest.raises(ConfigError, match="waits for the agent's own keyword"):
        start(
            Categorization,
            settings(
                categorization_file=path,
                instance="self",
                service_url="https://mailbox.example.test",
                service_token="t",
            ),
        )
