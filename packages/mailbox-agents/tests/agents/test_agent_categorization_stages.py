"""The chain of categorization through the runtime: the keywords of its list,
and the stage of each entry of ``then``:
docs/mailbox-agents/concept/agent-categorization.md."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from benethos_mailbox_agents.agents.categorization.agent import Categorization
from benethos_mailbox_agents.agents.categorization.lists import read_chain

from ..agents_fake import wire_message
from ..agents_helpers import Wired, actions, mail, run, settings, wired


def listed(keyword_stage: str | None = None, move_stage: str | None = None) -> Any:
    keyword: dict[str, Any] = {"keyword": "agent-hosting"}
    move: dict[str, Any] = {"move": "Invoices/Hosting"}
    if keyword_stage:
        keyword["stage"] = keyword_stage
    if move_stage:
        move["stage"] = move_stage
    return {
        "dimensions": [
            {
                "name": "partner",
                "categories": [
                    {
                        "name": "Hosting",
                        "senders": ["*@hosting.example"],
                        "then": [move, keyword],
                    }
                ],
            }
        ]
    }


def agent(tmp_path: Path, chain: Any, stage: str = "full") -> Categorization:
    path = tmp_path / "categorization.json"
    path.write_text(json.dumps(chain), encoding="utf-8")
    return Categorization(settings(stage=stage, categorization_file=path))


@pytest.fixture
async def stage_world(tmp_path: Path) -> AsyncIterator[Wired]:
    async with wired(tmp_path) as found:
        found.service.add(
            wire_message("hosting", sender="billing@hosting.example"), change=None
        )
        yield found


async def test_a_keyword_of_the_list_is_set_with_the_move(
    stage_world: Wired, tmp_path: Path
) -> None:
    assert await run(stage_world, "hosting", agent(tmp_path, listed())) == "done"

    found = mail(stage_world, "hosting")
    assert found["folder_ids"] == ["inv-hosting"]
    assert sorted(found["keywords"]) == ["agent-categorized", "agent-hosting"]
    assert actions(stage_world, "hosting") == [
        ("add_keyword", "agent-hosting", True),
        ("move_to_folder", "Invoices/Hosting", True),
        ("add_keyword", "agent-categorized", True),
    ]


async def test_an_entry_in_shadow_is_recorded_while_the_agent_acts_in_full(
    stage_world: Wired, tmp_path: Path
) -> None:
    chain = listed(keyword_stage="shadow")

    assert await run(stage_world, "hosting", agent(tmp_path, chain)) == "done"

    found = mail(stage_world, "hosting")
    assert found["folder_ids"] == ["inv-hosting"]
    assert found["keywords"] == ["agent-categorized"]
    assert actions(stage_world, "hosting") == [
        ("add_keyword", "agent-hosting", False),
        ("move_to_folder", "Invoices/Hosting", True),
        ("add_keyword", "agent-categorized", True),
    ]


async def test_in_suggest_the_keywords_are_set_and_the_move_recorded(
    stage_world: Wired, tmp_path: Path
) -> None:
    sorter = agent(tmp_path, listed(), stage="suggest")

    assert await run(stage_world, "hosting", sorter) == "done"

    found = mail(stage_world, "hosting")
    assert found["folder_ids"] == ["inbox"]
    assert found["keywords"] == ["agent-hosting"]
    assert actions(stage_world, "hosting") == [
        ("add_keyword", "agent-hosting", True),
        ("move_to_folder", "Invoices/Hosting", False),
        ("add_keyword", "agent-categorized", False),
    ]


@pytest.mark.parametrize("word", ["suggest", "keyword"])
async def test_a_move_whose_entry_says_suggest_is_recorded_in_full(
    stage_world: Wired, tmp_path: Path, word: str
) -> None:
    """keyword, the word of the middle stage before 2026-11-27, holds the
    move as suggest does."""
    chain = listed(move_stage=word)

    assert await run(stage_world, "hosting", agent(tmp_path, chain)) == "done"

    found = mail(stage_world, "hosting")
    assert found["folder_ids"] == ["inbox"]
    assert found["keywords"] == ["agent-hosting"]


def test_an_entry_keeps_its_stage_as_written_so_the_version_stays() -> None:
    """A list written with the former word keeps the version it had, so no
    message is decided anew for the change of word."""
    chain = listed(move_stage="keyword")

    assert read_chain(chain).version == "list-a3a10179de13"
    assert read_chain(listed(move_stage="suggest")).version != "list-a3a10179de13"
