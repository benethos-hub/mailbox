"""The caller and its accounts, read from /v1/me, the same for both clients."""

from __future__ import annotations

from collections.abc import Callable

from benethos_mailbox_client import Me, MeAccount, Sending

from ..fake_api import ME, FakeApi


async def test_me(make_client: Callable) -> None:
    api = FakeApi(ME)
    me = await make_client(api).me()
    assert api.call() == ("GET", "/v1/me", {}, None)
    assert me == Me(
        accounts=[
            MeAccount(
                id="acc_1",
                email="me@example.com",
                display_name="Me",
                operations=frozenset({"list_messages"}),
                warnings=frozenset({"reads_and_sends"}),
                sending=(Sending(("a@x.org",), 5, 4),),
                capabilities=frozenset({"flags"}),
            ),
            MeAccount(
                id="acc_2",
                email="two@example.com",
                display_name=None,
                operations=frozenset(),
                warnings=frozenset(),
            ),
        ],
        operations=frozenset({"list_users"}),
    )
