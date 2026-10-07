"""Grant constraints on sending and the audit of sends (CONCEPT 7.5, 7.7)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.data.models import (
    Grant,
)
from benethos_mailbox_service.data.providers.memory import MemoryProvider
from benethos_mailbox_service.domain.rights.access import (
    Access,
    SendLimit,
    pattern_covers,
    recipient_matches,
)

from ...conftest import ADMIN, bearer_for


def mail(*to: str, subject: str = "Hi") -> dict[str, object]:
    return {"to": [{"email": a} for a in to], "subject": subject, "text": "Hello"}


def outbox(services: Services, account_id: str) -> list[list[str]]:
    provider = services.adapters.get(account_id)
    assert isinstance(provider, MemoryProvider)
    return [recipients for _, recipients, _ in provider.outbox]


def sender(services: Services, account_id: str, **limits: object) -> dict[str, str]:
    return bearer_for(
        services,
        Grant.model_validate({"accounts": [account_id], "allow": ["send"], **limits}),
    )


# --- patterns -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("pattern", "address", "matches"),
    [
        ("*", "anyone@anywhere.org", True),
        ("*@example.org", "Bob@Example.ORG", True),
        ("*@example.org", "bob@sub.example.org", False),
        ("*@example.org", "bob@example.org.evil", False),
        ("bob@example.org", "BOB@example.org", True),
        ("bob@example.org", "bobby@example.org", False),
        # Local parts some servers route on to another host.
        ("*@example.org", "bob%evil.org@example.org", False),
        ("*@example.org", "evil.org!bob@example.org", False),
        ("bob%evil.org@example.org", "bob%evil.org@example.org", True),
    ],
)
def test_recipient_matches(pattern: str, address: str, matches: bool) -> None:
    assert recipient_matches(pattern, address) is matches


@pytest.mark.parametrize(
    ("outer", "inner", "covers"),
    [
        ("*", "*", True),
        ("*", "*@a.org", True),
        ("*@a.org", "*", False),
        ("*@a.org", "*@A.org", True),
        ("*@a.org", "bob@a.org", True),
        ("bob@a.org", "*@a.org", False),
        ("bob@a.org", "bob@a.org", True),
    ],
)
def test_pattern_covers(outer: str, inner: str, covers: bool) -> None:
    assert pattern_covers(outer, inner) is covers


def test_a_star_among_recipients_means_anyone() -> None:
    access = Access(
        "usr_1", "u", [Grant(accounts=["acc_1"], allow=["send"], recipients=["*"])]
    )
    assert access.send_limits("send_message", "acc_1") == [SendLimit(None, None)]


def test_grant_patterns_are_checked() -> None:
    with pytest.raises(ValueError):
        Grant(accounts=["a"], allow=["send"], recipients=["bob"])
    with pytest.raises(ValueError):
        Grant(accounts=["a"], allow=["send"], recipients=["*@*.a.org"])
    with pytest.raises(ValueError):
        Grant(accounts=["a"], allow=["send"], max_sends_per_day=0)


# --- through the API ------------------------------------------------------------------


def test_only_allowed_recipients(
    app_client: TestClient, services: Services, account_id: str
) -> None:
    headers = sender(services, account_id, recipients=["*@example.org"])
    url = f"/v1/accounts/{account_id}/send"
    ok = app_client.post(url, json=mail("bob@example.org"), headers=headers)
    assert ok.status_code == 200
    refused = app_client.post(
        url, json=mail("bob@example.org", "eve@evil.test"), headers=headers
    )
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "recipient_not_allowed"
    assert "eve@evil.test" in refused.json()["error"]["message"]
    assert outbox(services, account_id) == [["bob@example.org"]]


def test_bcc_counts_as_a_recipient(
    app_client: TestClient, services: Services, account_id: str
) -> None:
    headers = sender(services, account_id, recipients=["*@example.org"])
    body = {**mail("bob@example.org"), "bcc": [{"email": "eve@evil.test"}]}
    answer = app_client.post(
        f"/v1/accounts/{account_id}/send", json=body, headers=headers
    )
    assert answer.status_code == 403
    assert outbox(services, account_id) == []


def test_a_reply_is_checked_against_the_original_sender(
    app_client: TestClient, services: Services, account_id: str
) -> None:
    """The messages of the fixture come from alice@example.com."""
    headers = bearer_for(
        services,
        Grant(
            accounts=[account_id],
            allow=["send", "mail.read"],
            recipients=["*@example.org"],
        ),
    )
    reply = {"text": "Thanks", "reference": {"message_id": "m1", "action": "reply"}}
    page = app_client.get(f"/v1/accounts/{account_id}/messages", headers=headers)
    reply["reference"]["message_id"] = page.json()["items"][0]["id"]  # type: ignore[index]
    answer = app_client.post(
        f"/v1/accounts/{account_id}/send", json=reply, headers=headers
    )
    assert answer.status_code == 403
    assert "alice@example.com" in answer.json()["error"]["message"]


def test_send_limit(
    app_client: TestClient, services: Services, account_id: str
) -> None:
    headers = sender(services, account_id, max_sends_per_day=2)
    url = f"/v1/accounts/{account_id}/send"
    for n in range(2):
        answer = app_client.post(
            url, json=mail("a@x.org", subject=str(n)), headers=headers
        )
        assert answer.status_code == 200
    stopped = app_client.post(url, json=mail("a@x.org", subject="3"), headers=headers)
    assert stopped.status_code == 429
    assert stopped.json()["error"]["code"] == "send_limit_reached"
    assert 0 < int(stopped.headers["Retry-After"]) <= 24 * 3600
    assert len(outbox(services, account_id)) == 2


def test_a_retry_with_its_key_is_not_counted(
    app_client: TestClient, services: Services, account_id: str
) -> None:
    headers = {
        **sender(services, account_id, max_sends_per_day=1),
        "Idempotency-Key": "k",
    }
    url = f"/v1/accounts/{account_id}/send"
    first = app_client.post(url, json=mail("a@x.org"), headers=headers)
    again = app_client.post(url, json=mail("a@x.org"), headers=headers)
    assert (first.status_code, again.status_code) == (200, 200)
    assert again.json() == first.json()
    assert len(outbox(services, account_id)) == 1


def test_constraints_count_per_grant(
    app_client: TestClient, services: Services, account_id: str
) -> None:
    """Colleagues without a limit, anyone else once a day."""
    headers = bearer_for(
        services,
        Grant(accounts=[account_id], allow=["send"], recipients=["*@example.org"]),
        Grant(accounts=[account_id], allow=["send"], max_sends_per_day=1),
    )
    url = f"/v1/accounts/{account_id}/send"
    for n in range(3):
        colleague = mail("bob@example.org", subject=str(n))
        assert app_client.post(url, json=colleague, headers=headers).status_code == 200
    stranger = app_client.post(url, json=mail("x@other.test"), headers=headers)
    assert stranger.status_code == 429  # three sends already in 24 hours
    # Both at once fit no single grant: the colleague grant does not allow
    # the stranger, the other has used up its day.
    both = app_client.post(
        url, json=mail("bob@example.org", "x@other.test"), headers=headers
    )
    assert both.status_code == 429


def test_a_draft_is_checked_when_sent(
    app_client: TestClient, services: Services, account_id: str
) -> None:
    headers = bearer_for(
        services,
        Grant(accounts=[account_id], allow=["drafts"]),
        Grant(accounts=[account_id], allow=["send"], recipients=["*@example.org"]),
    )
    drafts = f"/v1/accounts/{account_id}/drafts"
    draft = app_client.post(drafts, json=mail("eve@evil.test"), headers=headers).json()
    sent = app_client.post(f"{drafts}/{draft['id']}/send", headers=headers)
    assert sent.status_code == 403
    assert outbox(services, account_id) == []


def test_the_admin_has_no_limits(
    client: TestClient, services: Services, account_id: str
) -> None:
    for n in range(3):
        answer = client.post(
            f"/v1/accounts/{account_id}/send", json=mail("a@x.org", subject=str(n))
        )
        assert answer.status_code == 200


# --- the audit ------------------------------------------------------------------------


def test_every_attempt_is_in_the_audit(
    app_client: TestClient, client: TestClient, services: Services, account_id: str
) -> None:
    headers = sender(services, account_id, recipients=["*@example.org"])
    url = f"/v1/accounts/{account_id}/send"
    app_client.post(url, json=mail("bob@example.org"), headers=headers)
    app_client.post(url, json=mail("eve@evil.test"), headers=headers)
    page = client.get(f"/v1/accounts/{account_id}/sends").json()
    denied, sent = page["items"]
    assert (sent["outcome"], denied["outcome"]) == ("sent", "denied")
    assert sent["recipients"] == ["bob@example.org"]
    assert sent["message_id_header"]
    assert denied["error"] == "recipient_not_allowed"
    assert sent["user_id"] == denied["user_id"] != "admin"
    assert sent["credential_id"].startswith("tok_")
    assert "Hello" not in str(page)  # never content


def test_the_audit_names_the_token(client: TestClient, account_id: str) -> None:
    client.post(f"/v1/accounts/{account_id}/send", json=mail("a@x.org"))
    [record] = client.get(f"/v1/accounts/{account_id}/sends").json()["items"]
    assert record["credential_id"].startswith("tok_")


def test_the_audit_is_paged(client: TestClient, account_id: str) -> None:
    for n in range(3):
        client.post(
            f"/v1/accounts/{account_id}/send", json=mail("a@x.org", subject=str(n))
        )
    url = f"/v1/accounts/{account_id}/sends"
    first = client.get(url, params={"limit": 2}).json()
    second = client.get(url, params={"limit": 2, "cursor": first["next_cursor"]}).json()
    ids = [r["id"] for r in first["items"] + second["items"]]
    assert len(ids) == len(set(ids)) == 3
    assert second["next_cursor"] is None
    assert client.get(url, params={"cursor": "nonsense"}).status_code == 400


def test_the_audit_across_accounts_keeps_a_deleted_one(
    client: TestClient, services: Services, account_id: str
) -> None:
    client.post(f"/v1/accounts/{account_id}/send", json=mail("a@x.org"))
    assert client.delete(f"/v1/accounts/{account_id}").status_code == 204
    page = services.mailbox.outgoing.list_all_sends(ADMIN, limit=10)
    assert [r.account_id for r in page.items] == [account_id]
    # A grant on named accounts audits those alone.
    named = Access("usr_a", "a", [Grant(accounts=["acc_other"], allow=["audit"])])
    assert services.mailbox.outgoing.list_all_sends(named, limit=10).items == []


def test_the_audit_of_every_account(
    app_client: TestClient, client: TestClient, services: Services, account_id: str
) -> None:
    other = client.post(
        "/v1/accounts", json={"provider": "memory", "email": "o@example.com"}
    ).json()["id"]
    for account in (account_id, other):
        client.post(f"/v1/accounts/{account}/send", json=mail("a@x.org"))
    first = client.get("/v1/sends", params={"limit": 1}).json()
    second = client.get(
        "/v1/sends", params={"limit": 1, "cursor": first["next_cursor"]}
    ).json()
    assert {r["account_id"] for r in first["items"] + second["items"]} == {
        account_id,
        other,
    }
    auditor = bearer_for(services, Grant(accounts=[account_id], allow=["audit"]))
    mine = app_client.get("/v1/sends", headers=auditor).json()["items"]
    assert [r["account_id"] for r in mine] == [account_id]
    sender_only = sender(services, account_id)
    assert app_client.get("/v1/sends", headers=sender_only).json()["items"] == []
    # Each list goes by its own right, as the lists of messages and
    # changes do: a grant naming the one operation opens the one list.
    across = bearer_for(
        services, Grant(accounts=[account_id], allow=["list_all_sends"])
    )
    found = app_client.get("/v1/sends", headers=across).json()["items"]
    assert [r["account_id"] for r in found] == [account_id]
    one = f"/v1/accounts/{account_id}/sends"
    assert app_client.get(one, headers=across).status_code == 403
    single = bearer_for(services, Grant(accounts=[account_id], allow=["list_sends"]))
    assert app_client.get("/v1/sends", headers=single).json()["items"] == []
    assert app_client.get(one, headers=single).status_code == 200


def test_the_audit_filters(
    app_client: TestClient, client: TestClient, services: Services, account_id: str
) -> None:
    headers = sender(services, account_id, recipients=["*@example.org"])
    url = f"/v1/accounts/{account_id}/send"
    app_client.post(url, json=mail("bob@example.org"), headers=headers)
    app_client.post(url, json=mail("eve@evil.test"), headers=headers)
    client.post(url, json=mail("Carol@Example.org"))
    me = client.get("/v1/me").json()["user_id"]
    for listing in (f"/v1/accounts/{account_id}/sends", "/v1/sends"):

        def recipients(listing: str = listing, **params: str) -> list[str]:
            page = client.get(listing, params=params).json()
            return [r for record in page["items"] for r in record["recipients"]]

        assert recipients(outcome="denied") == ["eve@evil.test"]
        assert recipients(recipient="EXAMPLE.org") == [
            "Carol@Example.org",
            "bob@example.org",
        ]
        assert recipients(user=me) == ["Carol@Example.org"]
        assert recipients(user=me, outcome="denied") == []
        assert recipients(after="2999-01-01T00:00:00Z") == []
        assert len(recipients(before="2999-01-01T00:00:00+02:00")) == 3
        assert len(recipients()) == 3
        # A time without a zone is not one, nor an outcome there is not.
        for wrong in ({"after": "2026-10-06T10:00:00"}, {"outcome": "lost"}):
            assert client.get(listing, params=wrong).status_code == 422


def test_the_audit_needs_its_right(
    app_client: TestClient, services: Services, account_id: str
) -> None:
    url = f"/v1/accounts/{account_id}/sends"
    headers = sender(services, account_id)
    assert app_client.get(url, headers=headers).status_code == 403
    auditor = bearer_for(services, Grant(accounts=[account_id], allow=["audit"]))
    assert app_client.get(url, headers=auditor).status_code == 200
