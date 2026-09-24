from __future__ import annotations

from fastapi.testclient import TestClient

from benethos_mailbox_api.data.models import Attachment
from benethos_mailbox_api.main import Services


def test_folders(client: TestClient, account_id: str) -> None:
    folders = client.get(f"/v1/accounts/{account_id}/folders").json()
    assert {f["role"] for f in folders} == {"inbox", "sent", "drafts"}


def test_messages_paginate_with_cursor(client: TestClient, account_id: str) -> None:
    url = f"/v1/accounts/{account_id}/messages"
    first = client.get(url, params={"folder": "inbox", "limit": 3}).json()
    assert [m["id"] for m in first["items"]] == ["m0", "m1", "m2"]
    assert first["next_cursor"]

    second = client.get(url, params={"limit": 3, "cursor": first["next_cursor"]})
    page = second.json()
    assert [m["id"] for m in page["items"]] == ["m3", "m4"]
    assert page["next_cursor"] is None


def test_messages_filter(client: TestClient, account_id: str) -> None:
    url = f"/v1/accounts/{account_id}/messages"
    assert len(client.get(url, params={"unread": True}).json()["items"]) == 2
    found = client.get(url, params={"q": "invoice"}).json()["items"]
    assert {m["id"] for m in found} == {"m1", "m3"}


def test_summary_uses_from_and_omits_body(client: TestClient, account_id: str) -> None:
    item = client.get(f"/v1/accounts/{account_id}/messages").json()["items"][0]
    assert item["from"]["email"] == "alice@example.com"
    assert "text_body" not in item


def test_get_message(client: TestClient, account_id: str) -> None:
    message = client.get(f"/v1/accounts/{account_id}/messages/m2").json()
    assert message["text_body"] == "body 2"
    missing = client.get(f"/v1/accounts/{account_id}/messages/nope")
    assert missing.status_code == 404


def test_limit_is_bounded(client: TestClient, account_id: str) -> None:
    url = f"/v1/accounts/{account_id}/messages"
    assert client.get(url, params={"limit": 0}).status_code == 422
    assert client.get(url, params={"limit": 201}).status_code == 422


def test_raw_source(client: TestClient, account_id: str) -> None:
    response = client.get(f"/v1/accounts/{account_id}/messages/m2/raw")
    assert response.status_code == 200
    assert response.headers["content-type"] == "message/rfc822"
    assert response.content.startswith(b"Subject: Hello 2")


def test_attachment_download(
    client: TestClient, account_id: str, services: Services
) -> None:
    adapter = services.accounts.provider(account_id)
    message = adapter.messages[0]
    message.attachments.append(
        Attachment(
            id="att_0", filename="Grüße.pdf", content_type="application/pdf", size=3
        )
    )
    adapter.attachment_data[("m0", "att_0")] = b"PDF"
    url = f"/v1/accounts/{account_id}/messages/m0/attachments/att_0"
    response = client.get(url)
    assert response.status_code == 200
    assert response.content == b"PDF"
    assert response.headers["content-type"] == "application/pdf"
    assert (
        "filename*=UTF-8''Gr%C3%BC%C3%9Fe.pdf"
        in response.headers["content-disposition"]
    )
    assert client.get(url.replace("att_0", "att_9")).status_code == 404
