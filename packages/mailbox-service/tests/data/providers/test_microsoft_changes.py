"""The ``microsoft`` adapter against a Graph mailbox in memory: changing
messages and folders."""

from __future__ import annotations

import httpx
import pytest

from benethos_mailbox_service.data.models import MessageUpdate
from benethos_mailbox_service.data.protocols.http import ApiClient
from benethos_mailbox_service.data.providers.microsoft import MicrosoftProvider
from benethos_mailbox_service.errors import (
    BadRequestError,
    ConflictError,
    NotFoundError,
    NotSupportedError,
    ProviderUnavailableError,
)

from ...graph_fake import TOKEN, FakeGraph
from .test_microsoft import Tokens, adapter


@pytest.fixture
def graph() -> FakeGraph:
    return FakeGraph()


# --- changing -------------------------------------------------------------------------


async def test_flags_and_move_keep_the_id(graph: FakeGraph) -> None:
    message_id = graph.add_message()
    archive = graph.new_folder("Archive", graph.root)
    results = await adapter(graph).update_messages(
        [message_id, "missing"],
        MessageUpdate(unread=False, starred=True, folder_ids=[archive]),
    )
    moved = results[message_id]
    assert not isinstance(moved, Exception)
    assert moved.id == message_id and moved.folder_ids == [archive]
    assert not moved.unread and moved.starred
    assert isinstance(results["missing"], NotFoundError)


async def test_categories_added_and_taken_off(graph: FakeGraph) -> None:
    message_id = graph.add_message(categories=["Red", "Work"])
    [changed] = (
        await adapter(graph).update_messages(
            [message_id],
            MessageUpdate(add_keywords=["urgent", "work"], remove_keywords=["red"]),
        )
    ).values()
    assert not isinstance(changed, Exception)
    # Those it keeps as Outlook spells them, one it has not added twice.
    assert graph.messages[message_id]["categories"] == ["Work", "urgent"]
    assert changed.keywords == ["work", "urgent"]


async def test_keywords_with_a_dollar_answer_501(graph: FakeGraph) -> None:
    """Outlook keeps no `$answered`: refused, and nothing else changed."""
    message_id = graph.add_message(categories=["Work"])
    draft_id = graph.add_message(isDraft=True)
    provider = adapter(graph)
    for changes in (
        MessageUpdate(unread=False, add_keywords=["$answered"]),
        MessageUpdate(keywords=["work", "$junk"]),
        MessageUpdate(remove_keywords=["$draft"]),
    ):
        target = draft_id if changes.remove_keywords else message_id
        [refused] = (await provider.update_messages([target], changes)).values()
        assert isinstance(refused, NotSupportedError)
    assert graph.messages[message_id]["isRead"] is False
    assert graph.messages[message_id]["categories"] == ["Work"]
    # What it has already, or has not, is no change.
    [kept] = (
        await provider.update_messages(
            [draft_id],
            MessageUpdate(keywords=["$draft", "Plan"], remove_keywords=None),
        )
    ).values()
    assert not isinstance(kept, Exception) and kept.keywords == ["plan", "$draft"]
    [same] = (
        await provider.update_messages(
            [message_id], MessageUpdate(remove_keywords=["$answered"])
        )
    ).values()
    assert not isinstance(same, Exception)


async def test_a_graph_message_is_in_one_folder(graph: FakeGraph) -> None:
    message_id = graph.add_message()
    archive = graph.new_folder("Archive", graph.root)
    [refused] = (
        await adapter(graph).update_messages(
            [message_id], MessageUpdate(add_folder_ids=[archive])
        )
    ).values()
    assert isinstance(refused, BadRequestError)


async def test_trash_then_for_good(graph: FakeGraph) -> None:
    message_id = graph.add_message()
    provider = adapter(graph)
    [trashed] = (await provider.delete_messages([message_id], permanent=False)).values()
    assert not isinstance(trashed, Exception) and trashed is not None
    assert trashed.folder_ids == [graph.well_known["deleteditems"]]
    [again] = (await provider.delete_messages([message_id], permanent=False)).values()
    assert isinstance(again, ConflictError)
    [gone] = (await provider.delete_messages([message_id], permanent=True)).values()
    assert gone is None and message_id not in graph.messages


async def test_message_headers_come_in_one_batch(graph: FakeGraph) -> None:
    ids = [graph.add_message(subject=f"m{n}") for n in range(3)]
    provider = adapter(graph)
    before = len(graph.requests)  # the fake answers a batch through itself
    found = await provider.message_headers([*ids, "AAMk999="])
    posted = [r for r in graph.requests[before:] if r.method == "POST"]
    assert [r.url.path for r in posted] == ["/v1.0/$batch"]
    assert set(found) == set(ids)
    assert all((v.message_id or "").startswith("<") for v in found.values())


async def test_for_good_from_the_inbox(graph: FakeGraph) -> None:
    message_id = graph.add_message()
    provider = adapter(graph)
    [gone] = (await provider.delete_messages([message_id], permanent=True)).values()
    assert gone is None and message_id not in graph.messages


async def test_a_top_level_rename_does_not_move(graph: FakeGraph) -> None:
    provider = adapter(graph)
    top = await provider.create_folder("Work", None)
    await provider.update_folder(top.id, "Working", None)
    moves = [r for r in graph.requests if r.url.path.endswith("/move")]
    assert moves == []


async def test_graph_asking_to_wait_is_left_alone(graph: FakeGraph) -> None:
    now = [0.0]
    provider = MicrosoftProvider(
        Tokens(TOKEN),
        ApiClient(transport=httpx.MockTransport(graph)),
        clock=lambda: now[0],
    )
    graph.next_answer = httpx.Response(
        429,
        json={"error": {"code": "TooManyRequests", "message": "slow down"}},
        headers={"Retry-After": "30"},
    )
    with pytest.raises(ProviderUnavailableError, match="retry after 30s"):
        await provider.list_folders()
    before = len(graph.requests)  # the fake answers a batch through itself
    with pytest.raises(ProviderUnavailableError, match="next attempt in 30s"):
        await provider.list_folders()
    assert len(graph.requests) == before
    now[0] += 31
    await provider.list_folders()


async def test_folders_are_created_renamed_moved_deleted(graph: FakeGraph) -> None:
    provider = adapter(graph)
    top = await provider.create_folder("Work", None)
    inner = await provider.create_folder("Inner", top.id)
    assert inner.parent_id == top.id
    renamed = await provider.update_folder(inner.id, "Inside", top.id)
    assert renamed.name == "Inside" and renamed.id == inner.id
    lifted = await provider.update_folder(inner.id, "Inside", None)
    # The mailbox's root is Graph's parent of the top: for us there is none.
    assert lifted.parent_id is None and top.parent_id is None
    listed = {f.id: f.parent_id for f in await provider.list_folders()}
    assert listed[top.id] is None and listed[inner.id] is None
    assert await provider.folder_contents(inner.id) == []
    await provider.delete_folder(inner.id)
    assert inner.id not in graph.folders
