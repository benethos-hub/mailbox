"""Sending a message and a draft, each with its Idempotency-Key, the same
for both clients."""

from __future__ import annotations

from collections.abc import Callable

from benethos_mailbox_client import Sent

from ..fake_api import BODY, SENT, FakeApi


async def test_send_message(make_client: Callable) -> None:
    api = FakeApi(SENT)
    found = await make_client(api).send_message("acc_1", BODY, "key-1")
    assert api.call() == ("POST", "/v1/accounts/acc_1/send", {}, BODY)
    assert api.seen[0].headers["idempotency-key"] == "key-1"
    assert found == Sent("<m@x>", ["b@x.org"])


async def test_send_draft(make_client: Callable) -> None:
    api = FakeApi({})
    found = await make_client(api).send_draft("acc_1", "drf_1", "key-2")
    path = "/v1/accounts/acc_1/drafts/drf_1/send"
    assert api.call() == ("POST", path, {}, None)
    assert api.seen[0].headers["idempotency-key"] == "key-2"
    assert found == Sent(None, [])
