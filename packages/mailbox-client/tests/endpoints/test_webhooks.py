"""Webhooks changed and given a new secret, the same for both clients."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from benethos_mailbox_client import Secret, Webhook

from ..fake_api import FakeApi

WEBHOOK = {
    "id": "whk_1",
    "url": "https://hooks.example.org/x",
    "events": ["message.created"],
    "accounts": None,
    "user_id": "usr_1",
    "created_at": "2026-10-09T12:00:00Z",
    "last_delivery_at": None,
    "last_error": None,
}


async def test_update_webhook_sends_only_what_changes(make_client: Callable) -> None:
    api = FakeApi(WEBHOOK)
    found = await make_client(api).update_webhook("whk_1", url=WEBHOOK["url"])
    assert api.call() == (
        "PATCH",
        "/v1/webhooks/whk_1",
        {},
        {"url": "https://hooks.example.org/x"},
    )
    assert found == Webhook(
        id="whk_1",
        url="https://hooks.example.org/x",
        events=("message.created",),
        accounts=None,
        user_id="usr_1",
        created_at=datetime(2026, 10, 9, 12, tzinfo=UTC),
        last_delivery_at=None,
        last_error=None,
    )


async def test_accounts_none_is_every_account(make_client: Callable) -> None:
    api = FakeApi(WEBHOOK)
    await make_client(api).update_webhook("whk_1", accounts=None)
    assert api.call()[3] == {"accounts": None}
    listed = FakeApi({**WEBHOOK, "accounts": ["acc_1"]})
    found = await make_client(listed).update_webhook(
        "whk_1", events=["message.sent"], accounts=["acc_1"]
    )
    assert listed.call()[3] == {"events": ["message.sent"], "accounts": ["acc_1"]}
    assert found.accounts == ("acc_1",)


async def test_a_new_secret_is_kept_out_of_any_line(make_client: Callable) -> None:
    api = FakeApi({"webhook_id": "whk_1", "secret": "whsec_new"})
    renewed = await make_client(api).renew_webhook_secret("whk_1")
    assert api.call() == ("POST", "/v1/webhooks/whk_1/secret", {}, None)
    assert renewed.webhook_id == "whk_1"
    assert renewed.secret.get_secret_value() == "whsec_new"
    assert "whsec_new" not in repr(renewed) and "whsec_new" not in str(renewed.secret)
    assert renewed.secret == Secret("whsec_new")
