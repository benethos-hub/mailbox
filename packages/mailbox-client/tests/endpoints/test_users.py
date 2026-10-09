"""Users listed, made, changed and deleted, and a password set, the same
for both clients."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from benethos_mailbox_client import Grant, User

from ..fake_api import USER, FakeApi

GRANT = Grant(
    accounts=("acc_1",),
    allow=("mail.read", "send"),
    recipients=("*@example.org",),
    max_sends_per_day=20,
    expires_at=datetime(2026, 12, 31, 23, tzinfo=UTC),
)


async def test_list_users(make_client: Callable) -> None:
    api = FakeApi({"items": [USER]})
    found = await make_client(api).list_users(ui_sign_in=False, limit=20)
    assert api.call() == (
        "GET",
        "/v1/users",
        {"ui_sign_in": "false", "limit": "20"},
        None,
    )
    assert found.next_cursor is None
    assert found.items == [
        User(
            id="usr_1",
            name="desktop",
            roles=("readers",),
            service=(),
            grants=(GRANT,),
            disabled=False,
            ui_sign_in=False,
            has_password=False,
            must_change=False,
            last_sign_in_at=None,
            second_factor=False,
        )
    ]


async def test_create_user_writes_its_grants(make_client: Callable) -> None:
    api = FakeApi(USER, status=201)
    found = await make_client(api).create_user("desktop", grants=[GRANT])
    assert api.call() == (
        "POST",
        "/v1/users",
        {},
        {
            "name": "desktop",
            "grants": [
                {
                    "accounts": ["acc_1"],
                    "allow": ["mail.read", "send"],
                    "recipients": ["*@example.org"],
                    "max_sends_per_day": 20,
                    "expires_at": "2026-12-31T23:00:00+00:00",
                }
            ],
        },
    )
    assert found.grants == (GRANT,)


async def test_get_update_and_delete_a_user(make_client: Callable) -> None:
    api = FakeApi(USER)
    assert (await make_client(api).get_user("usr_1")).name == "desktop"
    assert api.call()[:2] == ("GET", "/v1/users/usr_1")
    changed = FakeApi({**USER, "disabled": True})
    found = await make_client(changed).update_user("usr_1", disabled=True)
    assert changed.call() == ("PATCH", "/v1/users/usr_1", {}, {"disabled": True})
    assert found.disabled is True
    gone = FakeApi()
    assert await make_client(gone).delete_user("usr_1") is None
    assert gone.call()[:2] == ("DELETE", "/v1/users/usr_1")


async def test_a_one_time_password_is_shown_once_and_never_in_a_line(
    make_client: Callable,
) -> None:
    api = FakeApi({"password": "a one-time password", "must_change": True})
    made = await make_client(api).set_password("usr_1")
    assert api.call() == ("POST", "/v1/users/usr_1/password", {}, {})
    assert made.password is not None
    assert made.password.get_secret_value() == "a one-time password"
    assert "a one-time password" not in repr(made)
    given = FakeApi({"password": None, "must_change": True})
    chosen = await make_client(given).set_password("usr_1", "chosen by the caller")
    assert given.call()[3] == {"password": "chosen by the caller"}
    assert chosen.password is None and chosen.must_change is True
