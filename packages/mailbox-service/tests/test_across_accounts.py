from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.models import (
    Folder,
    FolderRole,
    Grant,
    Message,
    ProviderType,
)
from benethos_mailbox_service.data.providers import CredentialReader, ProviderSettings
from benethos_mailbox_service.data.providers.memory import MemoryProvider
from benethos_mailbox_service.errors import ProviderUnavailableError
from benethos_mailbox_service.main import Services, build_services, create_app

from .conftest import bearer_for, create_account

START = datetime(2026, 9, 1, tzinfo=UTC)


class Flaky(MemoryProvider):
    fail = False

    async def list_messages(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        if self.fail:
            raise ProviderUnavailableError("the mail server is not reachable")
        return await super().list_messages(*args, **kwargs)


def _messages(prefix: str, hours: list[int], folder: str = "inbox") -> list[Message]:
    return [
        Message(
            id=f"{prefix}{h}",
            folder_ids=[folder],
            subject=f"{prefix}{h}",
            date=START + timedelta(hours=h),
        )
        for h in hours
    ]


@pytest.fixture
def world() -> tuple[Services, TestClient, list[str], list[Flaky]]:
    adapters = [
        Flaky(messages=_messages("a", [9, 7, 5, 3, 1])),
        Flaky(messages=_messages("b", [10, 8, 2])),
        Flaky(
            folders=[Folder(id="archive", name="Archive", role=FolderRole.ARCHIVE)],
            messages=_messages("c", [6, 4], folder="archive"),
        ),
    ]
    by_name = dict(zip("abc", adapters, strict=True))

    def factory(
        kind: ProviderType, settings: ProviderSettings, credentials: CredentialReader
    ) -> Flaky:
        return by_name[str(settings["name"])]

    settings = Settings(storage="memory", api_key=SecretStr("k"))
    services = build_services(settings, provider_factory=factory)
    ids = [
        create_account(
            services.accounts,
            ProviderType.MEMORY,
            f"{n}@example.com",
            settings={"name": n},
        ).id
        for n in "abc"
    ]
    client = TestClient(
        create_app(settings, services), headers={"Authorization": "Bearer k"}
    )
    return services, client, ids, adapters


def _walk(client: TestClient, limit: int, **params: object) -> list[list[str]]:
    pages = []
    cursor = None
    while True:
        query = {"limit": limit, **params, **({"cursor": cursor} if cursor else {})}
        body = client.get("/v1/messages", params=query).json()
        pages.append([m["subject"] for m in body["items"]])
        cursor = body["next_cursor"]
        if cursor is None:
            return pages


def test_every_message_once_newest_first(world) -> None:  # type: ignore[no-untyped-def]
    _, client, _, _ = world
    pages = _walk(client, limit=3)
    flat = [s for page in pages for s in page]
    assert flat == ["b10", "a9", "b8", "a7", "c6", "a5", "c4", "a3", "b2", "a1"]
    assert all(len(page) <= 3 for page in pages)


@pytest.mark.parametrize("limit", [1, 2, 4, 50])
def test_order_holds_for_any_page_size(world, limit: int) -> None:  # type: ignore[no-untyped-def]
    _, client, _, _ = world
    flat = [s for page in _walk(client, limit=limit) for s in page]
    assert flat == ["b10", "a9", "b8", "a7", "c6", "a5", "c4", "a3", "b2", "a1"]


def test_items_carry_their_account(world) -> None:  # type: ignore[no-untyped-def]
    _, client, ids, _ = world
    items = client.get("/v1/messages", params={"limit": 2}).json()["items"]
    assert [i["account_id"] for i in items] == [ids[1], ids[0]]


def test_chosen_accounts_only(world) -> None:  # type: ignore[no-untyped-def]
    _, client, ids, _ = world
    flat = [
        s for page in _walk(client, limit=10, accounts=[ids[2], ids[1]]) for s in page
    ]
    assert flat == ["b10", "b8", "c6", "c4", "b2"]


def test_folder_role_per_account(world) -> None:  # type: ignore[no-untyped-def]
    _, client, _, _ = world
    archive = _walk(client, limit=10, folder="archive")
    assert archive == [["c6", "c4"]]
    inbox = [s for page in _walk(client, limit=10, folder="inbox") for s in page]
    assert "c6" not in inbox
    assert inbox[0] == "b10"


def test_rights_filter_without_a_word(world) -> None:  # type: ignore[no-untyped-def]
    services, client, ids, _ = world
    headers = bearer_for(services, Grant(accounts=[ids[0]], allow=["mail.read"]))
    body = client.get(
        "/v1/messages",
        params={"accounts": [ids[0], ids[1], "acc_ghost"], "limit": 10},
        headers=headers,
    ).json()
    assert [m["subject"] for m in body["items"]] == ["a9", "a7", "a5", "a3", "a1"]
    assert body["incomplete"] == []


def test_a_failing_account_does_not_keep_the_cursor_alive(world) -> None:  # type: ignore[no-untyped-def]
    _, client, ids, adapters = world
    adapters[1].fail = True
    # The failed account keeps its place while the others deliver. Once
    # nothing but failed accounts is left, the list ends.
    pages = _walk(client, limit=50)
    assert pages == [["a9", "a7", "c6", "a5", "c4", "a3", "a1"], []]


def test_a_failing_account_leaves_the_page_incomplete(world) -> None:  # type: ignore[no-untyped-def]
    _, client, ids, adapters = world
    adapters[1].fail = True
    body = client.get("/v1/messages", params={"limit": 3}).json()
    assert [m["subject"] for m in body["items"]] == ["a9", "a7", "c6"]
    assert body["incomplete"] == [
        {
            "account_id": ids[1],
            "code": "provider_unavailable",
            "message": "the mail server is not reachable",
        }
    ]
    assert client.get(f"/v1/accounts/{ids[1]}").json()["status"] == "unreachable"

    # The failed account keeps its place and joins again later.
    adapters[1].fail = False
    rest = client.get(
        "/v1/messages", params={"limit": 50, "cursor": body["next_cursor"]}
    ).json()
    assert [m["subject"] for m in rest["items"]] == [
        "b10",
        "b8",
        "a5",
        "c4",
        "a3",
        "b2",
        "a1",
    ]


def test_invalid_cursor(world) -> None:  # type: ignore[no-untyped-def]
    _, client, _, _ = world
    for cursor in ["nonsense", "x_!!!", "x_" + "e30"[:-1]]:
        response = client.get("/v1/messages", params={"cursor": cursor})
        assert response.status_code == 400


def test_per_account_listing_also_names_the_account(world) -> None:  # type: ignore[no-untyped-def]
    _, client, ids, _ = world
    items = client.get(f"/v1/accounts/{ids[0]}/messages").json()["items"]
    assert {i["account_id"] for i in items} == {ids[0]}
    message = client.get(f"/v1/accounts/{ids[0]}/messages/a9").json()
    assert message["account_id"] == ids[0]
