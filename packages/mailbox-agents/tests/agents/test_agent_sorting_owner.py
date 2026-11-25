"""The chain of sorting keeps the owner's choice: a message moved by hand
does not wander back, whatever the list says since:
docs/mailbox-agents/concept/agent-sorting.md."""

from __future__ import annotations

import copy
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from benethos_mailbox_agents.agents.sorting.agent import Sorting
from benethos_mailbox_agents.records import Event, MessageRef

from ..agents_fake import ACCOUNT, wire_message
from ..agents_helpers import Wired, mail, run, settings, wired

CHAIN: dict[str, Any] = {
    "dimensions": [
        {
            "name": "partner",
            "categories": [
                {
                    "name": "Hosting",
                    "senders": ["*@hosting.example"],
                    "then": [{"move": "Invoices/Hosting"}],
                }
            ],
        }
    ]
}


def agent(tmp_path: Path, chain: dict[str, Any], name: str = "sorting.json") -> Sorting:
    path = tmp_path / name
    path.write_text(json.dumps(chain), encoding="utf-8")
    return Sorting(settings(stage="full", sorting_file=path))


@pytest.fixture
async def owner_world(tmp_path: Path) -> AsyncIterator[Wired]:
    async with wired(tmp_path) as found:
        found.service.add(
            wire_message("hosting", sender="billing@hosting.example"), change=None
        )
        yield found


@pytest.mark.parametrize("keyword_taken_off", [False, True])
async def test_a_message_moved_by_hand_stays_under_a_changed_list(
    owner_world: Wired, tmp_path: Path, keyword_taken_off: bool
) -> None:
    assert await run(owner_world, "hosting", agent(tmp_path, CHAIN)) == "done"
    assert mail(owner_world, "hosting")["folder_ids"] == ["inv-hosting"]
    # The owner moves it elsewhere, and may take the keyword off.
    moved = mail(owner_world, "hosting")
    moved["folder_ids"] = ["inv-telco"]
    if keyword_taken_off:
        moved["keywords"] = []
    changed = copy.deepcopy(CHAIN)
    changed["dimensions"][0]["categories"][0]["then"].append({"move_below": "Sub"})
    later = agent(tmp_path, changed, "changed.json")

    await run(owner_world, "hosting", later, again=True)

    assert mail(owner_world, "hosting")["folder_ids"] == ["inv-telco"]
    # No folder is made for a move that is not taken.
    assert owner_world.service.made() == []


def test_a_move_by_hand_sets_nothing_off_also_on_arrival_in_folders(
    tmp_path: Path,
) -> None:
    chain = {**CHAIN, "on": {"arrival": "folders"}}
    found = agent(tmp_path, chain)
    ref = MessageRef(account_id=ACCOUNT, message_id="hosting")
    at = datetime(2026, 11, 25, tzinfo=UTC)

    assert found.select(Event(type="message.updated", ref=ref, at=at)) is None
