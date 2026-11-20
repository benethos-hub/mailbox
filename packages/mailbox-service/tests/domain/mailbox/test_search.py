"""Search filters (CONCEPT 6.6): what the API takes. IMAP SEARCH is
data/providers/test_imap_search.py's."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

# --- the API ------------------------------------------------------------------------


def test_filters_through_the_api(client: TestClient, account_id: str) -> None:
    url = f"/v1/accounts/{account_id}/messages"
    page = client.get(url, params={"subject": "invoice", "unread": False}).json()
    assert [m["subject"] for m in page["items"]] == ["Invoice 3"]
    page = client.get(url, params={"from": "alice", "after": "2026-09-04"}).json()
    assert sorted(m["subject"] for m in page["items"]) == ["Hello 4", "Invoice 3"]


def test_a_folder_by_its_role(client: TestClient, account_id: str) -> None:
    url = f"/v1/accounts/{account_id}/messages"
    assert len(client.get(url, params={"folder": "inbox"}).json()["items"]) == 5
    missing = client.get(url, params={"folder": "trash"})
    assert missing.status_code == 501
    assert "trash" in missing.json()["error"]["message"]


@pytest.mark.parametrize("field", ["q", "from", "to", "subject"])
def test_search_text_on_one_line(
    client: TestClient, account_id: str, field: str
) -> None:
    for url in ("/v1/messages", f"/v1/accounts/{account_id}/messages"):
        answer = client.get(url, params={field: "a\r\nX1 DELETE INBOX"})
        assert answer.status_code == 422


def test_filters_across_accounts(client: TestClient, account_id: str) -> None:
    page = client.get("/v1/messages", params={"subject": "hello"}).json()
    assert [m["subject"] for m in page["items"]] == ["Hello 4", "Hello 2", "Hello 0"]
