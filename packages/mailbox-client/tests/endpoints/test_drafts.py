"""The drafts of an account, the same for both clients."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from ..fake_api import BODY, FakeApi


async def test_list_drafts(make_client: Callable) -> None:
    api = FakeApi({"items": [], "next_cursor": None})
    await make_client(api).list_drafts("acc_1", 10)
    assert api.call() == ("GET", "/v1/accounts/acc_1/drafts", {"limit": "10"}, None)


async def test_create_draft(make_client: Callable) -> None:
    api = FakeApi({"id": "drf_1"})
    found = await make_client(api).create_draft("acc_1", BODY)
    assert api.call() == ("POST", "/v1/accounts/acc_1/drafts", {}, BODY)
    assert found.id == "drf_1"


@pytest.mark.parametrize(
    ("keep", "sent"), [(None, {}), (["att_0"], {"keep_attachments": ["att_0"]})]
)
async def test_update_draft(
    make_client: Callable, keep: list[str] | None, sent: dict[str, Any]
) -> None:
    api = FakeApi({"id": "drf_2"})
    await make_client(api).update_draft("acc_1", "drf_1", BODY, keep)
    path = "/v1/accounts/acc_1/drafts/drf_1"
    assert api.call() == ("PUT", path, {}, {**BODY, **sent})


async def test_delete_draft(make_client: Callable) -> None:
    api = FakeApi(None)
    assert await make_client(api).delete_draft("acc_1", "drf_1") is None
    assert api.call() == ("DELETE", "/v1/accounts/acc_1/drafts/drf_1", {}, None)
