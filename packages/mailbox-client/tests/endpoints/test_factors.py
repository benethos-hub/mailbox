"""A user's second factor, the same for both clients."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from benethos_mailbox_client import SecondFactor, TotpDevice

from ..fake_api import FakeApi


async def test_get_second_factor(make_client: Callable) -> None:
    api = FakeApi(
        {
            "totp": [
                {"id": "tfa_1", "name": "Phone", "created_at": "2026-10-09T12:00:00Z"}
            ],
            "recovery_codes_left": 9,
        }
    )
    found = await make_client(api).get_second_factor("usr_1")
    assert api.call() == ("GET", "/v1/users/usr_1/second-factor", {}, None)
    assert found == SecondFactor(
        totp=(
            TotpDevice("tfa_1", "Phone", datetime(2026, 10, 9, 12, tzinfo=UTC), None),
        ),
        recovery_codes_left=9,
    )


async def test_remove_one_device_or_every_one(make_client: Callable) -> None:
    one = FakeApi()
    assert await make_client(one).remove_totp_device("usr_1", "tfa_1") is None
    assert one.call() == (
        "DELETE",
        "/v1/users/usr_1/second-factor/totp/tfa_1",
        {},
        None,
    )
    every = FakeApi()
    assert await make_client(every).remove_second_factor("usr_1") is None
    assert every.call() == ("DELETE", "/v1/users/usr_1/second-factor", {}, None)
