"""Roles, the same for both clients."""

from __future__ import annotations

from collections.abc import Callable

from benethos_mailbox_client import Grant, Role

from ..fake_api import FakeApi

ROLE = {
    "id": "readers",
    "service": ["audit"],
    "grants": [{"accounts": ["*"], "allow": ["mail.read"]}],
}
READERS = Role("readers", ("audit",), (Grant(("*",), ("mail.read",)),))


async def test_list_and_get_roles(make_client: Callable) -> None:
    api = FakeApi([ROLE])
    assert await make_client(api).list_roles() == [READERS]
    assert api.call() == ("GET", "/v1/roles", {}, None)
    one = FakeApi(ROLE)
    assert await make_client(one).get_role("my role") == READERS
    assert one.seen[0].url.raw_path == b"/v1/roles/my%20role"


async def test_create_role(make_client: Callable) -> None:
    api = FakeApi(ROLE, status=201)
    made = await make_client(api).create_role(
        "readers", service=["audit"], grants=[Grant(("*",), ("mail.read",))]
    )
    assert api.call() == (
        "POST",
        "/v1/roles",
        {},
        {
            "id": "readers",
            "service": ["audit"],
            "grants": [{"accounts": ["*"], "allow": ["mail.read"]}],
        },
    )
    assert made == READERS


async def test_replace_role_names_every_right(make_client: Callable) -> None:
    api = FakeApi({**ROLE, "service": []})
    await make_client(api).replace_role(
        "readers", grants=[Grant(("*",), ("mail.read",))]
    )
    assert api.call() == (
        "PUT",
        "/v1/roles/readers",
        {},
        {"service": [], "grants": [{"accounts": ["*"], "allow": ["mail.read"]}]},
    )


async def test_delete_role(make_client: Callable) -> None:
    api = FakeApi()
    assert await make_client(api).delete_role("readers") is None
    assert api.call() == ("DELETE", "/v1/roles/readers", {}, None)
