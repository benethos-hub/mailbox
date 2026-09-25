"""The change feed for Microsoft: Graph delta queries per folder, through
the real adapter against a fake Graph."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any, TypeVar

import httpx
import pytest

from benethos_mailbox_service.data.http import ApiClient
from benethos_mailbox_service.data.providers import Capability, MailProvider
from benethos_mailbox_service.data.providers.microsoft import MicrosoftProvider
from benethos_mailbox_service.data.storage import InMemoryMessageIndexRepository
from benethos_mailbox_service.domain.changes import ChangeFeed
from benethos_mailbox_service.domain.sync import SyncService
from benethos_mailbox_service.errors import ChangesExpiredError

from .graph_fake import TOKEN, FakeGraph
from .test_microsoft import Tokens

T = TypeVar("T")
ACC = "acc_ms"


class OneAdapter:
    """What SyncService needs of Adapters, for one account."""

    def __init__(self, provider: MailProvider) -> None:
        self.provider = provider

    def capabilities(self, account_id: str) -> frozenset[Capability]:
        return self.provider.capabilities

    async def call(
        self, account_id: str, operation: Callable[[MailProvider], Awaitable[T]]
    ) -> T:
        return await operation(self.provider)


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 9, 26, 10, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def later(self, graph: FakeGraph, minutes: int = 5) -> None:
        self.now += timedelta(minutes=minutes)
        graph.clock = self.now.strftime("%Y-%m-%dT%H:%M:%SZ")  # type: ignore[attr-defined]


@pytest.fixture
def graph() -> FakeGraph:
    graph = FakeGraph()
    graph.clock = "2026-09-26T09:00:00Z"  # type: ignore[attr-defined]
    graph.add_message(subject="Old one")
    graph.add_message(subject="Old two")
    return graph


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def sync(graph: FakeGraph, clock: Clock) -> SyncService:
    provider = MicrosoftProvider(
        Tokens(TOKEN), ApiClient(transport=httpx.MockTransport(graph))
    )
    adapters: Any = OneAdapter(provider)
    return SyncService(
        adapters, InMemoryMessageIndexRepository(), feed=ChangeFeed(), clock=clock
    )


def recorded(sync: SyncService) -> list[tuple[str, str]]:
    return [(e.change.type, e.change.id) for e in sync.feed.after([ACC], 0, limit=100)]


def test_microsoft_is_watched_without_an_index(sync: SyncService) -> None:
    assert not sync.mapped(ACC)
    assert sync.watched(ACC)


async def test_the_first_pass_records_nothing(sync: SyncService) -> None:
    await sync.sync_account(ACC)
    assert recorded(sync) == []


async def test_a_new_mail(sync: SyncService, graph: FakeGraph, clock: Clock) -> None:
    await sync.sync_account(ACC)
    clock.later(graph)
    new = graph.add_message(subject="New")
    await sync.sync_account(ACC)
    assert recorded(sync) == [("message.created", new)]


async def test_a_flag_set_by_another_client(
    sync: SyncService, graph: FakeGraph, clock: Clock
) -> None:
    [old, _] = graph.messages
    await sync.sync_account(ACC)
    clock.later(graph)
    graph.other_client_changes(old, isRead=True)
    await sync.sync_account(ACC)
    assert recorded(sync) == [("message.updated", old)]


async def test_a_move_is_an_update_not_a_deletion(
    sync: SyncService, graph: FakeGraph, clock: Clock
) -> None:
    [old, _] = graph.messages
    await sync.sync_account(ACC)
    clock.later(graph)
    graph.other_client_changes(old, parentFolderId=graph.well_known["junkemail"])
    await sync.sync_account(ACC)
    assert recorded(sync) == [("message.updated", old)]


async def test_a_move_into_a_new_folder_is_an_update(
    sync: SyncService, graph: FakeGraph, clock: Clock
) -> None:
    [old, _] = graph.messages
    await sync.sync_account(ACC)
    clock.later(graph)
    folder = graph.new_folder("Projects", graph.root)
    graph.other_client_changes(old, parentFolderId=folder)
    await sync.sync_account(ACC)
    assert recorded(sync) == [("message.updated", old)]


async def test_a_deletion(sync: SyncService, graph: FakeGraph, clock: Clock) -> None:
    [old, _] = graph.messages
    await sync.sync_account(ACC)
    clock.later(graph)
    del graph.messages[old]
    await sync.sync_account(ACC)
    assert recorded(sync) == [("message.deleted", old)]


async def test_nothing_changed(
    sync: SyncService, graph: FakeGraph, clock: Clock
) -> None:
    await sync.sync_account(ACC)
    clock.later(graph)
    await sync.sync_account(ACC)
    assert recorded(sync) == []


async def test_a_token_graph_no_longer_keeps_starts_the_folder_again(
    sync: SyncService, graph: FakeGraph, clock: Clock
) -> None:
    [old, _] = graph.messages
    await sync.sync_account(ACC)
    graph.delta_links.clear()
    clock.later(graph)
    graph.other_client_changes(old, isRead=True)
    await sync.sync_account(ACC)
    # Nothing to tell for that pass, and the next one works again.
    assert recorded(sync) == []
    clock.later(graph)
    graph.other_client_changes(old, isRead=False)
    await sync.sync_account(ACC)
    assert recorded(sync) == [("message.updated", old)]


# --- the adapter --------------------------------------------------------------------


async def test_a_delta_follows_its_pages(graph: FakeGraph) -> None:
    graph.delta_page = 1
    provider = MicrosoftProvider(
        Tokens(TOKEN), ApiClient(transport=httpx.MockTransport(graph))
    )
    inbox = graph.well_known["inbox"]
    first = await provider.folder_changes(inbox, None)
    assert len(first.changed) == 2
    assert first.changed[0].created == datetime(2026, 9, 26, 9, 0, tzinfo=UTC)
    new = graph.add_message(subject="New")
    del graph.messages[next(iter(graph.messages))]
    later = await provider.folder_changes(inbox, first.token)
    assert [m.id for m in later.changed] == [new]
    assert len(later.removed) == 1
    assert later.token.startswith("/me/mailFolders/")


async def test_a_lost_token_is_expired(graph: FakeGraph) -> None:
    provider = MicrosoftProvider(
        Tokens(TOKEN), ApiClient(transport=httpx.MockTransport(graph))
    )
    inbox = graph.well_known["inbox"]
    first = await provider.folder_changes(inbox, None)
    graph.delta_links.clear()
    with pytest.raises(ChangesExpiredError):
        await provider.folder_changes(inbox, first.token)


async def test_a_delta_asks_for_immutable_ids(graph: FakeGraph) -> None:
    provider = MicrosoftProvider(
        Tokens(TOKEN), ApiClient(transport=httpx.MockTransport(graph))
    )
    await provider.folder_changes(graph.well_known["inbox"], None)
    [request] = graph.requests[-1:]
    assert "ImmutableId" in request.headers["prefer"]
