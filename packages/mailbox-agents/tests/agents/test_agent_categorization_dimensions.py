"""The list of categorization with dimensions: how it is read, what it refuses,
and that a list of groups keeps its version:
docs/mailbox-agents/concept/agent-categorization.md."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from benethos_mailbox_agents.agents.categorization.lists import GROUP, load_chain
from benethos_mailbox_agents.errors import ConfigError

from .categorization_chain_helpers import CHAIN, written


def chain(**changes: Any) -> dict[str, Any]:
    found = copy.deepcopy(CHAIN)
    found.update(changes)
    return found


def refused(tmp_path: Path, listed: dict[str, Any], says: str) -> str:
    """The list is refused with ``says``, and its message quotes no rule
    and no topic."""
    with pytest.raises(ConfigError, match="categorization.json") as raised:
        load_chain(written(tmp_path, listed))
    message = raised.value.message
    assert says in message
    for rule in ("*@bank.example", "*@hosting.example"):
        assert rule not in message
    assert "Invoices of a provider" not in message
    return message


def test_a_list_of_groups_is_one_dimension_and_keeps_its_version(
    tmp_path: Path,
) -> None:
    """The same value as before the chain: a new one would take every
    message of the list up again."""
    listed = {
        "groups": [
            {"name": "Hosting", "folder": "Hosting", "senders": ["*@hosting.example"]}
        ]
    }

    found = load_chain(written(tmp_path, listed))

    assert found.version == "list-9c732a913e57"
    assert [d.name for d in found.chain.dimensions] == [GROUP]
    category = found.chain.first.categories[0]
    assert category.target == "Hosting"
    assert found.chain.on.arrival == "inbox"


def test_a_list_of_dimensions_is_read(tmp_path: Path) -> None:
    found = load_chain(written(tmp_path))

    assert [d.name for d in found.chain.dimensions] == ["partner", "kind"]
    assert found.chain.dimensions[1].when == {"partner": ("Bank", "Hosting")}
    bank = found.chain.first.named("Bank")
    assert bank is not None
    assert (bank.target, bank.priority) == ("Providers/Bank", 0)
    assert found.version.startswith("list-")


def test_the_version_follows_the_list(tmp_path: Path) -> None:
    first = load_chain(written(tmp_path)).version
    changed = chain()
    changed["dimensions"][0]["categories"][0]["priority"] = 1

    assert load_chain(written(tmp_path, changed)).version != first
    assert load_chain(written(tmp_path)).version == first


@pytest.mark.parametrize(
    ("change", "says"),
    [
        (lambda c: c.update(groups=[]), "groups or dimensions, not both"),
        (lambda c: c.update(dimensions=[]), "at least 1 item"),
        (
            lambda c: c["dimensions"].append(copy.deepcopy(c["dimensions"][0])),
            "two dimensions share the name 'partner'",
        ),
        (
            lambda c: c["dimensions"][0].update(name="Partner"),
            "lower case letters",
        ),
        (
            lambda c: c["dimensions"][0].update(when={"kind": ["Invoice"]}),
            "when names no earlier dimension",
        ),
        (
            lambda c: c["dimensions"][1].update(when={"partner": ["Telco"]}),
            "when names a category 'partner' does not have",
        ),
        (
            lambda c: c["dimensions"][0]["categories"][1].update(name="bank"),
            "two categories share the name 'bank'",
        ),
        (
            lambda c: c["dimensions"][0]["categories"][1].update(
                senders=["*@bank.example"]
            ),
            "is named by group 'Bank' as well",
        ),
        (
            lambda c: c["dimensions"][1]["categories"][1].update(recognize="ledger"),
            "category 'Notice': recognize names no recognizer",
        ),
        (
            lambda c: c["dimensions"][0]["categories"][0].update(senders=[]),
            "a category names senders, a topic, keywords or a recognizer",
        ),
        (
            lambda c: c["dimensions"][0]["categories"][0]["then"].append(
                {"forward": "x"}
            ),
            "names no action of keyword, move, move_below",
        ),
        (
            lambda c: c["dimensions"][0]["categories"][0]["then"].append(
                {"move": "Elsewhere"}
            ),
            "one move and one move_below at most",
        ),
        (
            lambda c: c["dimensions"][0]["categories"][0]["then"].append(
                {"keyword": "Bank"}
            ),
            "a keyword is agent-",
        ),
        (
            lambda c: c["dimensions"][0]["categories"][0]["then"].append(
                {"keyword": "agent-x", "move": "X"}
            ),
            "names one action",
        ),
        (
            lambda c: c["dimensions"][0]["categories"][1]["then"].__setitem__(
                0, {"move": "providers/Hosting"}
            ),
            "category 'Hosting': a folder differs from one of category 'Bank'",
        ),
        (
            lambda c: c["dimensions"][0]["categories"][0]["then"].__setitem__(
                0, {"move": "Providers/../Bank"}
            ),
            "a folder is names between /",
        ),
        (
            lambda c: c["dimensions"][0]["categories"][0]["then"].__setitem__(
                0, {"move": "Providers/Bank", "stage": "most"}
            ),
            "'shadow', 'suggest', 'keyword' or 'full'",
        ),
    ],
)
def test_a_wrong_list_is_refused_with_its_place(
    tmp_path: Path, change: Any, says: str
) -> None:
    listed = chain()
    change(listed)

    refused(tmp_path, listed, says)


def test_more_than_four_dimensions_are_refused(tmp_path: Path) -> None:
    listed = chain()
    extra = {"name": "Other", "senders": ["*@other.example"]}
    listed["dimensions"] += [
        {"name": f"extra_{number}", "categories": [extra]} for number in range(3)
    ]

    refused(tmp_path, listed, "at most 4 dimensions")


def test_more_than_two_dimensions_asking_the_model_are_refused(
    tmp_path: Path,
) -> None:
    listed = chain()
    asking = copy.deepcopy(listed["dimensions"][1])
    asking.update(name="tone", when={})
    listed["dimensions"].append(asking)
    listed["dimensions"].append({**copy.deepcopy(asking), "name": "mood"})

    refused(tmp_path, listed, "at most 2 recognizers of a list ask the model")


@pytest.mark.parametrize(
    ("change", "says"),
    [
        ({"on": {"keywords": ["agent-b*"]}}, "it would set itself off"),
        ({"on": {"keywords": ["Agent-X"]}}, "a keyword of on is lower case"),
        ({"on": {"arrival": None}}, "on names an arrival, keywords or both"),
        ({"mark_done": "yes"}, "mark_done: Input should be a valid boolean"),
        ({"on": {"arrival": "everywhere"}}, "'inbox' or 'folders'"),
    ],
)
def test_a_wrong_on_or_mark_done_is_refused_with_a_clear_message(
    tmp_path: Path, change: dict[str, Any], says: str
) -> None:
    refused(tmp_path, chain(**change), says)


def test_a_when_on_none_is_allowed(tmp_path: Path) -> None:
    listed = chain()
    listed["dimensions"][1]["when"] = {"partner": ["none"]}

    found = load_chain(written(tmp_path, listed))

    assert found.chain.dimensions[1].when == {"partner": ("none",)}
