"""Accounts listed, connected, changed, verified and removed, the same
for both clients."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from benethos_mailbox_client import Account, Paged, StoredCredential

from ..fake_api import ACCOUNT, FakeApi


async def test_list_accounts(make_client: Callable) -> None:
    api = FakeApi({"items": [ACCOUNT], "next_cursor": "c2"})
    found = await make_client(api).list_accounts(address="me@", limit=10)
    assert api.call() == (
        "GET",
        "/v1/accounts",
        {"address": "me@", "limit": "10"},
        None,
    )
    assert found == Paged(
        items=[
            Account(
                id="acc_1",
                provider="imap",
                email="me@example.com",
                display_name=None,
                status="connected",
                credentials=(
                    StoredCredential("password", datetime(2026, 10, 1, tzinfo=UTC)),
                ),
                settings={"host": "imap.example.com", "port": 993},
                capabilities=frozenset({"flags", "folders"}),
            )
        ],
        next_cursor="c2",
    )


async def test_create_account_sends_the_credentials_once(
    make_client: Callable,
) -> None:
    api = FakeApi(ACCOUNT, status=201)
    found = await make_client(api).create_account(
        "imap",
        "me@example.com",
        settings={"host": "imap.example.com"},
        credentials={"password": "not shown"},
    )
    assert api.call() == (
        "POST",
        "/v1/accounts",
        {},
        {
            "provider": "imap",
            "email": "me@example.com",
            "settings": {"host": "imap.example.com"},
            "credentials": {"password": "not shown"},
        },
    )
    assert found.id == "acc_1" and "not shown" not in repr(found)


async def test_get_verify_and_delete_an_account(make_client: Callable) -> None:
    api = FakeApi(ACCOUNT)
    assert (await make_client(api).get_account("acc_1")).email == "me@example.com"
    assert api.call()[:2] == ("GET", "/v1/accounts/acc_1")
    verified = FakeApi({**ACCOUNT, "status": "needs_reauth"})
    assert (
        await make_client(verified).verify_account("acc_1")
    ).status == "needs_reauth"
    assert verified.call()[:2] == ("POST", "/v1/accounts/acc_1/verify")
    gone = FakeApi()
    assert await make_client(gone).delete_account("acc_1") is None
    assert gone.call() == ("DELETE", "/v1/accounts/acc_1", {}, None)


async def test_update_account_leaves_out_what_stays(make_client: Callable) -> None:
    api = FakeApi(ACCOUNT)
    await make_client(api).update_account("acc_1", settings={"smtp_port": 465})
    assert api.call()[3] == {"settings": {"smtp_port": 465}}
    removed = FakeApi(ACCOUNT)
    await make_client(removed).update_account("acc_1", display_name=None)
    assert removed.call() == ("PATCH", "/v1/accounts/acc_1", {}, {"display_name": None})
