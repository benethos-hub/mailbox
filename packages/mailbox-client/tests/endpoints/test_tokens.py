"""The tokens of a user, the same for both clients."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from benethos_mailbox_client import Token

from ..fake_api import FakeApi

TOKEN = {
    "id": "tok_1",
    "user_id": "usr_1",
    "name": "laptop",
    "state": "active",
    "created_at": "2026-10-09T12:00:00Z",
    "expires_at": None,
    "last_used_at": "2026-10-09T13:00:00Z",
    "revoked_at": None,
}


async def test_list_tokens(make_client: Callable) -> None:
    api = FakeApi([TOKEN])
    found = await make_client(api).list_tokens("usr_1")
    assert api.call() == ("GET", "/v1/users/usr_1/tokens", {}, None)
    assert found == [
        Token(
            id="tok_1",
            user_id="usr_1",
            name="laptop",
            state="active",
            created_at=datetime(2026, 10, 9, 12, tzinfo=UTC),
            expires_at=None,
            last_used_at=datetime(2026, 10, 9, 13, tzinfo=UTC),
            revoked_at=None,
        )
    ]


async def test_a_new_tokens_secret_comes_once_and_in_no_line(
    make_client: Callable,
) -> None:
    api = FakeApi({**TOKEN, "token": "mbx_secret"}, status=201)
    until = datetime(2027, 1, 1, tzinfo=UTC)
    made = await make_client(api).create_token("usr_1", "laptop", until)
    assert api.call() == (
        "POST",
        "/v1/users/usr_1/tokens",
        {},
        {"name": "laptop", "expires_at": "2027-01-01T00:00:00+00:00"},
    )
    assert made.token.name == "laptop"
    assert made.secret.get_secret_value() == "mbx_secret"
    assert "mbx_secret" not in repr(made)


async def test_revoke_token(make_client: Callable) -> None:
    api = FakeApi()
    assert await make_client(api).revoke_token("usr_1", "tok_1") is None
    assert api.call() == ("DELETE", "/v1/users/usr_1/tokens/tok_1", {}, None)
