"""Instances of sorting that hand a message on by keywords: the
recognizer keyword, the sign of an instance that is done, and an
instance that waits for a keyword: docs/mailbox-agents/concept/sorting-chain.md."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from .sorting_chain_helpers import Scripted, context, decided, message, sorting


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
        sorting(tmp_path, kinds()), message("a@x.example", keywords=keywords), model
    )

    assert (found.label, found.details["match"], found.source) == (
        label,
        match,
        "baseline",
    )
    assert model.asked == []


def test_a_list_of_keywords_alone_asks_no_model(tmp_path: Path) -> None:
    assert not sorting(tmp_path, kinds()).asks_model()


async def test_with_mark_done_the_sign_is_set_also_for_none(tmp_path: Path) -> None:
    agent = sorting(tmp_path, kinds(mark_done=True))
    found = message("a@x.example")
    decision = await decided(agent, found, Scripted())

    requests = await agent.effect(decision, found, context(Scripted()))

    assert decision.label == "none"
    assert plain(requests) == [("add_keyword", "agent-sorted", False)]


async def test_with_mark_done_the_sign_comes_before_the_move(tmp_path: Path) -> None:
    agent = sorting(tmp_path, kinds(mark_done=True))
    found = message("a@x.example", keywords=["agent-partner-bank", "agent-invoice"])
    decision = await decided(agent, found, Scripted())

    requests = await agent.effect(decision, found, context(Scripted()))

    assert plain(requests)[0] == ("add_keyword", "agent-sorted", False)
    assert plain(requests)[-1] == (
        "move_to_folder",
        "Providers/Bank/Invoices",
        False,
    )


async def test_without_mark_done_the_sign_comes_with_a_move_alone(
    tmp_path: Path,
) -> None:
    agent = sorting(tmp_path, kinds())
    for keywords, signed in (
        (["agent-partner-bank"], False),
        (["agent-partner-bank", "agent-invoice"], True),
    ):
        found = message("a@x.example", keywords=keywords)
        decision = await decided(agent, found, Scripted())

        requests = await agent.effect(decision, found, context(Scripted()))

        assert (("add_keyword", "agent-sorted", False) in plain(requests)) is signed
