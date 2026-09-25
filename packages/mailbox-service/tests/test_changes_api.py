"""The change feed over the API: states, paging, expiry and rights."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service.common import opaque
from benethos_mailbox_service.data.models import AccountStatus, Grant, ProviderType
from benethos_mailbox_service.domain.changes import STATE
from benethos_mailbox_service.main import Services

from .conftest import bearer_for, create_account


def state_now(client: TestClient, url: str = "/v1/changes") -> str:
    answer = client.get(url)
    assert answer.status_code == 200
    assert answer.json()["changes"] == []
    assert answer.json()["more"] is False
    return str(answer.json()["state"])


def mark_read(client: TestClient, account_id: str, message_id: str) -> None:
    answer = client.patch(
        f"/v1/accounts/{account_id}/messages/{message_id}", json={"unread": False}
    )
    assert answer.status_code == 200


def test_without_since_only_the_current_state(
    client: TestClient, account_id: str
) -> None:
    state_now(client)
    state_now(client, f"/v1/accounts/{account_id}/changes")


def test_a_change_after_the_state(client: TestClient, account_id: str) -> None:
    since = state_now(client)
    mark_read(client, account_id, "m0")
    answer = client.get("/v1/changes", params={"since": since}).json()
    assert [(c["type"], c["id"], c["account_id"]) for c in answer["changes"]] == [
        ("message.updated", "m0", account_id)
    ]
    assert answer["more"] is False
    # Nothing new after the state it handed out.
    again = client.get("/v1/changes", params={"since": answer["state"]}).json()
    assert again["changes"] == []
    assert again["state"] == answer["state"]


def test_one_accounts_state_is_the_same_point(
    client: TestClient, account_id: str
) -> None:
    since = state_now(client, f"/v1/accounts/{account_id}/changes")
    mark_read(client, account_id, "m1")
    answer = client.get("/v1/changes", params={"since": since}).json()
    assert [c["id"] for c in answer["changes"]] == ["m1"]


def test_paging_with_more(client: TestClient, account_id: str) -> None:
    since = state_now(client)
    for message_id in ("m0", "m1", "m2"):
        mark_read(client, account_id, message_id)
    url = f"/v1/accounts/{account_id}/changes"
    first = client.get(url, params={"since": since, "limit": 2}).json()
    assert [c["id"] for c in first["changes"]] == ["m0", "m1"]
    assert first["more"] is True
    rest = client.get(url, params={"since": first["state"], "limit": 2}).json()
    assert [c["id"] for c in rest["changes"]] == ["m2"]
    assert rest["more"] is False


def test_the_accounts_filter(
    client: TestClient, services: Services, account_id: str
) -> None:
    other = create_account(services.accounts, ProviderType.MEMORY, "b@example.com")
    since = state_now(client)
    mark_read(client, account_id, "m0")
    mark_read(client, other.id, "m1")
    answer = client.get(
        "/v1/changes", params={"since": since, "accounts": [other.id]}
    ).json()
    assert [(c["account_id"], c["id"]) for c in answer["changes"]] == [(other.id, "m1")]


def test_a_state_that_is_not_one(client: TestClient) -> None:
    for since in ("nonsense", "chs_bm9uc2Vuc2U", "chs_LTE"):  # text, then -1
        answer = client.get("/v1/changes", params={"since": since})
        assert answer.status_code == 400, since
        assert answer.json()["error"]["code"] == "bad_request"


def test_a_state_never_handed_out_is_expired(
    client: TestClient, account_id: str
) -> None:
    mark_read(client, account_id, "m0")
    # A fresh database starts the numbers again: an old client is ahead.
    answer = client.get("/v1/changes", params={"since": opaque.encode(STATE, 999)})
    assert answer.status_code == 410
    assert answer.json()["error"]["code"] == "changes_expired"


def test_a_purged_state_answers_410(
    client: TestClient,
    services: Services,
    account_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    since = state_now(client)
    mark_read(client, account_id, "m0")
    later = state_now(client)
    week_later = datetime.now(UTC) + timedelta(days=8)
    monkeypatch.setattr(services.changes, "_clock", lambda: week_later)
    services.changes.purge()
    answer = client.get("/v1/changes", params={"since": since})
    assert answer.status_code == 410
    assert answer.json()["error"]["code"] == "changes_expired"
    # The state after the purged change still works.
    assert client.get("/v1/changes", params={"since": later}).status_code == 200


def test_the_feed_holds_only_accounts_the_caller_may_read(
    client: TestClient, services: Services, account_id: str
) -> None:
    other = create_account(services.accounts, ProviderType.MEMORY, "b@example.com")
    limited = TestClient(
        client.app,
        headers=bearer_for(services, Grant(accounts=[account_id], allow=["mail.read"])),
    )
    since = state_now(limited)
    mark_read(client, account_id, "m0")
    mark_read(client, other.id, "m1")
    answer = limited.get("/v1/changes", params={"since": since}).json()
    assert [c["account_id"] for c in answer["changes"]] == [account_id]
    # Asked for by name, the other account is still left out.
    named = limited.get(
        "/v1/changes", params={"since": since, "accounts": [other.id]}
    ).json()
    assert named["changes"] == []
    # Its own feed is not found at all.
    hidden = limited.get(f"/v1/accounts/{other.id}/changes")
    assert hidden.status_code == 404


def test_the_feed_of_one_account_needs_list_changes(
    client: TestClient, services: Services, account_id: str
) -> None:
    sender = TestClient(
        client.app,
        headers=bearer_for(services, Grant(accounts=[account_id], allow=["send"])),
    )
    answer = sender.get(f"/v1/accounts/{account_id}/changes")
    assert answer.status_code == 403
    assert "list_changes" in answer.json()["error"]["message"]


# --- events beyond the feed ---------------------------------------------------------


def test_a_send_is_an_event_the_feed_leaves_out(
    client: TestClient, services: Services, account_id: str
) -> None:
    since = state_now(client)
    answer = client.post(
        f"/v1/accounts/{account_id}/send",
        json={"to": [{"email": "bob@example.com"}], "subject": "Hi", "text": "x"},
    )
    assert answer.status_code == 200
    copy_id = answer.json()["sent_copy_id"]
    events = [
        (e.event.type, e.event.id)
        for e in services.changes.after([account_id], 0, limit=50)
    ]
    assert ("message.sent", copy_id) in events
    feed = client.get("/v1/changes", params={"since": since}).json()["changes"]
    assert "message.sent" not in {c["type"] for c in feed}


def test_an_account_that_needs_a_new_sign_in_is_an_event_once(
    services: Services, account_id: str
) -> None:
    services.adapters.set_status(account_id, AccountStatus.NEEDS_REAUTH)
    services.adapters.set_status(account_id, AccountStatus.NEEDS_REAUTH)
    events = services.changes.after([account_id], 0, limit=50)
    assert [(e.event.type, e.event.id) for e in events] == [
        ("account.needs_reauth", account_id)
    ]
