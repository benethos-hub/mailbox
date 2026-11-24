"""The topics of the list of sorting: what a topic and how far it goes
may be, and the version of a list with them."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from benethos_mailbox_agents.agents.sorting.agent import _version

from .sorting_helpers import groups, refused

TOPIC = "Mail about the project Alpha: the offer and the weekly status"


def _topical(**extra: Any) -> dict[str, Any]:
    return {"name": "Alpha", "folder": "Projects/Alpha", "topic": TOPIC, **extra}


@pytest.mark.parametrize(
    ("entries", "says"),
    [
        ([{"name": "A", "folder": "A"}], "group 'A': a group names senders, a topic"),
        (
            [
                {
                    "name": "A",
                    "folder": "A",
                    "senders": ["a@b.example"],
                    "by_topic": "act",
                }
            ],
            "group 'A': by_topic needs a topic",
        ),
        ([_topical(by_topic="move")], "by_topic"),
        ([_topical(topic="")], "group 'Alpha': a topic is not empty"),
        ([_topical(topic=f" {TOPIC}")], "no space at its ends"),
        ([_topical(topic="x" * 301)], "group 'Alpha': a topic has at most 300"),
        ([_topical(topic=f"{TOPIC}\nand more")], "group 'Alpha': a topic is one line"),
        ([_topical(topic=f"{TOPIC}\x07")], "a topic is one line"),
        ([_topical(topic=f"{TOPIC} more")], "a topic is one line"),
        ([_topical(topic=7)], "topic"),
        (
            [_topical(name="Al\npha")],
            "the name of a group with a topic is one line",
        ),
        (
            [
                _topical(senders=["*@client.example"]),
                {"name": "B", "folder": "B", "senders": ["*@client.example"]},
            ],
            "group 'B', sender 1 is named by group 'Alpha' as well",
        ),
        (
            [
                {"name": "B", "folder": "B", "senders": ["*@client.example"]},
                _topical(senders=["*@client.example"]),
            ],
            "group 'Alpha', sender 1 is named by group 'B' as well",
        ),
        (
            [
                {"name": f"G{n}", "folder": f"G{n}", "topic": f"Topic {n}"}
                for n in range(51)
            ],
            "more than 50 groups have a topic",
        ),
    ],
)
def test_a_wrong_topic_says_what_is_wrong(
    tmp_path: Path, entries: list[dict[str, Any]], says: str
) -> None:
    refused(tmp_path, entries, says)


def test_a_group_may_name_a_topic_alone() -> None:
    found = groups(_topical()).groups[0]

    assert (found.senders, found.topic, found.by_topic) == ((), TOPIC, "record")


def test_a_group_may_act_on_its_topic() -> None:
    assert groups(_topical(by_topic="act")).groups[0].by_topic == "act"


def test_groups_with_a_topic_may_share_a_sender() -> None:
    found = groups(
        _topical(senders=["*@client.example"], by_topic="act"),
        {
            "name": "Beta",
            "folder": "Projects/Beta",
            "senders": ["*@client.example"],
            "topic": "Mail about the project Beta: the migration of the shop",
        },
    )

    assert [g.name for g in found.groups] == ["Alpha", "Beta"]


def test_fifty_groups_may_have_a_topic() -> None:
    found = groups(
        *(
            {"name": f"G{n}", "folder": f"G{n}", "topic": f"Topic {n}"}
            for n in range(50)
        )
    )

    assert len(found.groups) == 50


def test_a_name_without_a_topic_is_not_held_to_one_line() -> None:
    entry = {"name": "Al\npha", "folder": "A", "senders": ["a@b.example"]}

    assert groups(entry).groups[0].name == "Al\npha"


def test_a_topic_and_how_far_it_goes_change_the_version() -> None:
    plain = {"name": "Alpha", "folder": "Alpha", "senders": ["*@client.example"]}
    versions = {
        _version(groups(plain)),
        _version(groups({**plain, "topic": TOPIC})),
        _version(groups({**plain, "topic": TOPIC + " too"})),
        _version(groups({**plain, "topic": TOPIC, "by_topic": "act"})),
    }

    assert len(versions) == 4
