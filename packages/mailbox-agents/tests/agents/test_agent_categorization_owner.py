"""The chain of categorization keeps the owner's choice: a message moved by hand
does not wander back, whatever the list says since:
docs/mailbox-agents/concept/agent-categorization.md."""

from __future__ import annotations

import copy
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from benethos_mailbox_agents.agents.categorization.agent import Categorization
from benethos_mailbox_agents.records import Event, FolderRef, MessageRef

from ..agents_fake import ACCOUNT, wire_message
from ..agents_helpers import Wired, actions, mail, run, settings, wired

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


def agent(
    tmp_path: Path, chain: dict[str, Any], name: str = "categorization.json"
) -> Categorization:
    path = tmp_path / name
    path.write_text(json.dumps(chain), encoding="utf-8")
    return Categorization(settings(stage="full", categorization_file=path))


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


FOLDERS: dict[str, Any] = {
    "on": {"arrival": "folders"},
    "dimensions": [
        {
            "name": "partner",
            "categories": [
                {
                    "name": "Hosting",
                    "senders": ["*@hosting.example"],
                    "then": [
                        {"move": "Providers/Hosting"},
                        {"move_below": "Sub"},
                        {"keyword": "agent-hosting"},
                    ],
                }
            ],
        }
    ],
}


@pytest.fixture
async def folder_world(tmp_path: Path) -> AsyncIterator[Wired]:
    async with wired(tmp_path) as found:
        for message_id, folder in (
            ("filed", "inv-hosting"),
            ("binned", "trash"),
            ("below-bin", "trash-sub"),
        ):
            found.service.add(
                wire_message(
                    message_id, sender="billing@hosting.example", folder_ids=[folder]
                ),
                change=None,
            )
        yield found


async def test_on_arrival_in_the_inbox_mail_in_a_folder_is_skipped(
    folder_world: Wired, tmp_path: Path
) -> None:
    inbox_only = {**FOLDERS, "on": {"arrival": "inbox"}}

    assert await run(folder_world, "filed", agent(tmp_path, inbox_only)) == "skipped"
    assert folder_world.service.writes() == []


async def test_on_arrival_in_folders_mail_goes_below_its_folder_and_not_out(
    folder_world: Wired, tmp_path: Path
) -> None:
    assert await run(folder_world, "filed", agent(tmp_path, FOLDERS)) == "done"

    found = mail(folder_world, "filed")
    assert [f["name"] for f in folder_world.service.made()] == ["Sub"]
    assert found["folder_ids"] != ["inv-hosting"]
    assert sorted(found["keywords"]) == ["agent-categorized", "agent-hosting"]
    assert actions(folder_world, "filed")[-2:] == [
        ("move_to_folder", "Invoices/Hosting/Sub", True),
        ("add_keyword", "agent-categorized", True),
    ]


@pytest.mark.parametrize(
    ("message_id", "state"), [("binned", "skipped"), ("below-bin", "done")]
)
async def test_on_arrival_in_folders_the_trash_is_never_touched(
    folder_world: Wired, tmp_path: Path, message_id: str, state: str
) -> None:
    assert await run(folder_world, message_id, agent(tmp_path, FOLDERS)) == state

    assert folder_world.service.writes() == []
    assert folder_world.service.made() == []


def test_backfill_takes_up_folders_without_a_role_on_arrival_in_folders(
    tmp_path: Path,
) -> None:
    mine = FolderRef(id="x", name="Mine", role=None, path="Mine")
    sent = FolderRef(id="s", name="Sent", role="sent", path="Sent")

    assert agent(tmp_path, FOLDERS).backfill_folder(mine)
    assert not agent(tmp_path, FOLDERS).backfill_folder(sent)
    assert not agent(tmp_path, CHAIN, "inbox.json").backfill_folder(mine)


async def test_a_sorted_message_put_back_is_not_moved_again_by_a_backfill(
    owner_world: Wired, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    assert await run(owner_world, "hosting", agent(tmp_path, CHAIN)) == "done"
    mail(owner_world, "hosting")["folder_ids"] = ["inbox"]
    mail(owner_world, "hosting")["keywords"] = []
    caplog.set_level("INFO")

    assert (
        await run(owner_world, "hosting", agent(tmp_path, CHAIN), again=True) == "done"
    )

    assert mail(owner_world, "hosting")["folder_ids"] == ["inbox"]
    names = [r.name.rsplit(".", 1)[-1] for r in caplog.records if ".actions." in r.name]
    assert "kept" in names
