"""The chain of sorting through the runtime: the keywords of its list,
and the stage of each entry of ``then``:
docs/mailbox-agents/concept/agent-sorting.md."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from benethos_mailbox_agents.agents.sorting.agent import Sorting

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


def agent(tmp_path: Path, chain: Any, stage: str = "full") -> Sorting:
    path = tmp_path / "sorting.json"
    path.write_text(json.dumps(chain), encoding="utf-8")
    return Sorting(settings(stage=stage, sorting_file=path))


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
    assert sorted(found["keywords"]) == ["agent-hosting", "agent-sorted"]
    assert actions(stage_world, "hosting") == [
        ("add_keyword", "agent-hosting", True),
        ("move_to_folder", "Invoices/Hosting", True),
        ("add_keyword", "agent-sorted", True),
    ]
