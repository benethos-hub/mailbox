"""The chain of categorization: dimensions in order, the recognizers and the
actions as registers, and what follows from the categories found:
docs/mailbox-agents/concept/agent-categorization.md."""

from __future__ import annotations

import copy
import dataclasses
from pathlib import Path
from typing import Any, ClassVar

import pytest

from benethos_mailbox_agents.agents.categorization import actions as chain_actions
from benethos_mailbox_agents.agents.categorization import recognizers
from benethos_mailbox_agents.agents.categorization.actions import (
    ChainAction,
    KeywordParams,
    Params,
)
from benethos_mailbox_agents.agents.categorization.dimensions import Dimension
from benethos_mailbox_agents.agents.categorization.plan import DISPLACED
from benethos_mailbox_agents.agents.categorization.recognizers import Choice, Recognizer
from benethos_mailbox_agents.contract import (
    Action,
    ActionRequest,
    Placed,
    Shown,
    ShownAction,
)
from benethos_mailbox_agents.records import Decision, FolderRef, MailMessage

from .categorization_chain_helpers import (
    CHAIN,
    QUOTE,
    Scripted,
    categorization,
    context,
    decided,
    message,
)


def plain(requests: list[ActionRequest]) -> list[tuple[str, str, bool]]:
    return [(r.action.value, r.folder or r.keyword or "", r.held) for r in requests]


async def effect(tmp_path: Path, chain: Any, found: MailMessage, *answers: Any) -> Any:
    agent = categorization(tmp_path, chain)
    model = Scripted(*answers)
    decision = await decided(agent, found, model)
    return decision, await agent.effect(decision, found, context(model))


# -- finding 3: the dimensions in order ------------------------------------------------


async def test_a_later_dimension_runs_after_the_categories_its_when_names(
    tmp_path: Path,
) -> None:
    model = Scripted({"group": "Invoice", "quote": QUOTE})

    found = await decided(categorization(tmp_path), message("a@bank.example"), model)

    assert (found.label, found.fields, found.source) == (
        "Bank",
        {"kind": "Invoice"},
        "model",
    )
    assert found.details["match"] == "group"
    assert found.details["kind.match"] == "topic"
    assert found.actionable
    assert len(model.asked) == 1


async def test_a_dimension_whose_when_does_not_hold_asks_nothing(
    tmp_path: Path,
) -> None:
    model = Scripted()

    found = await decided(
        categorization(tmp_path), message("a@elsewhere.example"), model
    )

    assert (found.label, found.fields, found.source) == ("none", {}, "baseline")
    assert model.asked == []


async def test_a_later_field_without_its_quote_is_dropped_alone(
    tmp_path: Path,
) -> None:
    model = Scripted({"group": "Invoice", "quote": "a sentence the mail lacks"})

    found = await decided(categorization(tmp_path), message("a@bank.example"), model)

    assert (found.label, found.fields, found.actionable) == ("Bank", {}, True)


async def test_a_first_dimension_without_its_quote_refuses_the_decision(
    tmp_path: Path,
) -> None:
    chain = copy.deepcopy(CHAIN)
    chain["dimensions"].reverse()
    chain["dimensions"][0]["when"] = {}
    chain["dimensions"][1]["when"] = {"kind": ["Invoice"]}
    model = Scripted({"group": "Invoice", "quote": "a sentence the mail lacks"})

    found = await decided(
        categorization(tmp_path, chain), message("a@bank.example"), model
    )

    assert found.refused == "evidence"


async def test_two_dimensions_ask_the_model_once_each(tmp_path: Path) -> None:
    chain = copy.deepcopy(CHAIN)
    chain["dimensions"][0]["categories"].append(
        {"name": "Shop", "topic": "Mail of a shop the owner buys from"}
    )
    chain["dimensions"][1]["when"] = {}
    model = Scripted(
        {"group": "Shop", "quote": QUOTE}, {"group": "Notice", "quote": QUOTE}
    )

    found = await decided(
        categorization(tmp_path, chain), message("a@elsewhere.example"), model
    )

    assert (found.label, found.fields) == ("Shop", {"kind": "Notice"})
    assert len(model.asked) == 2


# -- finding 2: the recognizers as a register ------------------------------------------


class Always(Recognizer):
    """A recognizer of a test: every category that names it, by code."""

    name = "always"
    version = "1"

    def asks_model(self, dimension: Dimension) -> bool:
        return False

    def baseline(self, dimension: Dimension, found: MailMessage) -> Choice | None:
        named = [c for c in dimension.categories if c.recognize == self.name]
        return Choice(named[0].name, {"match": "always"}) if named else None


async def test_a_recognizer_added_in_code_works_without_a_change_to_the_core(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(recognizers.RECOGNIZERS, "always", Always())
    chain = copy.deepcopy(CHAIN)
    chain["dimensions"][1]["categories"] = [
        {"name": "Any", "recognize": "always", "then": [{"keyword": "agent-any"}]}
    ]
    agent = categorization(tmp_path, chain)

    found = agent.baseline(message("a@bank.example"))

    assert (found.fields, found.details["kind.match"]) == ({"kind": "Any"}, "always")
    assert agent.prompt_version.endswith("-always-1")


# -- finding 4: what follows ---------------------------------------------------------


async def test_partner_and_kind_give_one_move_below_and_their_keywords(
    tmp_path: Path,
) -> None:
    _, requests = await effect(
        tmp_path,
        None,
        message("a@bank.example"),
        {"group": "Invoice", "quote": QUOTE},
    )

    assert plain(requests) == [
        ("add_keyword", "agent-bank", False),
        ("add_keyword", "agent-invoice", False),
        ("create_folder", "Providers", False),
        ("create_folder", "Providers/Bank", False),
        ("create_folder", "Providers/Bank/Invoices", False),
        ("move_to_folder", "Providers/Bank/Invoices", False),
        ("add_keyword", "agent-categorized", False),
    ]


async def test_a_kind_chosen_without_act_sets_its_keyword_only(
    tmp_path: Path,
) -> None:
    _, requests = await effect(
        tmp_path,
        None,
        message("a@hosting.example"),
        {"group": "Notice", "quote": QUOTE},
    )

    assert plain(requests) == [
        ("add_keyword", "agent-notice", False),
        ("create_folder", "Providers", False),
        ("create_folder", "Providers/Hosting", False),
        ("move_to_folder", "Providers/Hosting", False),
        ("add_keyword", "agent-categorized", False),
    ]


def two_moves(first: int = 0, second: int = 0, hold: bool = False) -> dict[str, Any]:
    """A partner and a project, each with a move, by sender alone."""
    return {
        "dimensions": [
            {
                "name": "partner",
                "categories": [
                    {
                        "name": "Bank",
                        "senders": ["*@bank.example"],
                        "priority": first,
                        "hold": hold,
                        "then": [{"move": "Providers/Bank"}],
                    }
                ],
            },
            {
                "name": "project",
                "categories": [
                    {
                        "name": "Alpha",
                        "senders": ["a@bank.example"],
                        "priority": second,
                        "then": [{"move": "Projects/Alpha"}],
                    }
                ],
            },
        ]
    }


@pytest.mark.parametrize(
    ("first", "second", "hold", "moved", "held", "displaced"),
    [
        (0, 0, False, "Providers/Bank", False, "project"),
        (0, 1, False, "Projects/Alpha", False, "partner"),
        (1, 0, True, "Providers/Bank", True, "project"),
    ],
)
async def test_of_two_moves_the_priority_decides_and_a_held_winner_holds(
    tmp_path: Path,
    first: int,
    second: int,
    hold: bool,
    moved: str,
    held: bool,
    displaced: str,
) -> None:
    decision, requests = await effect(
        tmp_path, two_moves(first, second, hold), message("a@bank.example")
    )

    moves = [r for r in requests if r.action is Action.MOVE_TO_FOLDER]
    assert [(r.folder, r.held) for r in moves] == [(moved, held)]
    assert decision.details[DISPLACED] == displaced


def test_an_action_sees_no_subject_no_sender_and_no_text() -> None:
    names = {f.name for f in dataclasses.fields(Placed)}

    assert names == {"ref", "folders", "keywords", "sender_check", "from_address"}
    hidden = next(f for f in dataclasses.fields(Placed) if f.name == "from_address")
    assert not hidden.repr
    assert not hidden.compare


class Flag(ChainAction):
    """An action of a test: one keyword, whatever the value says."""

    name = "flag"
    params: ClassVar[type[Params]] = KeywordParams
    primitives = frozenset({Action.ADD_KEYWORD})
    by_model = True

    def requests(
        self, params: Params, placed: Placed, *, held: bool, why: str
    ) -> list[ActionRequest]:
        return [
            ActionRequest(Action.ADD_KEYWORD, placed.ref, keyword="agent-flag", why=why)
        ]


async def test_an_action_added_in_code_works_without_a_change_to_the_core(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(chain_actions.ACTIONS, "flag", Flag())
    chain = two_moves()
    chain["dimensions"][0]["categories"][0]["then"] = [{"flag": "agent-x"}]

    _, requests = await effect(tmp_path, chain, message("a@bank.example"))

    assert ("add_keyword", "agent-flag", False) in plain(requests)


async def test_a_message_outside_the_inbox_is_not_moved_out(
    tmp_path: Path,
) -> None:
    elsewhere = FolderRef(id="x", name="Mine", role=None, path="Mine")

    _, requests = await effect(
        tmp_path,
        None,
        message("a@bank.example", folders=(elsewhere,)),
        {"group": "Invoice", "quote": QUOTE},
    )

    assert plain(requests) == [
        ("add_keyword", "agent-bank", False),
        ("add_keyword", "agent-invoice", False),
        ("create_folder", "Mine/Invoices", False),
        ("move_to_folder", "Mine/Invoices", False),
        ("add_keyword", "agent-categorized", False),
    ]


# -- finding 8: the report -----------------------------------------------------------


def test_the_report_names_each_dimension_and_what_became_of_its_categories(
    tmp_path: Path,
) -> None:
    def shown(
        label: str, kind: str | None, *done: tuple[Action, bool], **details: str
    ) -> Shown:
        fields = {} if kind is None else {"kind": kind}
        decision = Decision(
            label=label, source="baseline", fields=fields, details=details
        )
        return Shown(
            sender=None,
            decision=decision,
            actions=tuple(ShownAction(action, flag) for action, flag in done),
        )

    move = (Action.MOVE_TO_FOLDER, True)
    keyword = (Action.ADD_KEYWORD, True)
    items = [
        shown("Bank", "Invoice", keyword, move),
        shown("Bank", "Notice", keyword, move),
        shown("Hosting", "Notice", (Action.ADD_KEYWORD, False)),
        shown("none", None),
    ]

    lines = categorization(tmp_path).summarize(items)

    assert lines[:6] == [
        "partner:",
        "  Bank: 2 moved",
        "  Hosting: 1 not moved",
        "kind:",
        "  Invoice: 1 moved",
        "  Notice: 1 keyword set, 1 keyword recorded",
    ]


def test_the_report_counts_a_move_lost_to_the_priority_of_another(
    tmp_path: Path,
) -> None:
    decision = Decision(
        label="Bank",
        source="baseline",
        fields={"project": "Alpha"},
        details={DISPLACED: "partner"},
    )
    item = Shown(
        sender=None,
        decision=decision,
        actions=(ShownAction(Action.MOVE_TO_FOLDER, True),),
    )

    lines = categorization(tmp_path, two_moves()).summarize([item])

    assert lines == [
        "partner:",
        "  Bank: 1 displaced by priority",
        "project:",
        "  Alpha: 1 moved",
    ]
