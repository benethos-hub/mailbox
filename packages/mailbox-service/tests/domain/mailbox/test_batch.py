"""POST .../messages/batch: one action for many messages (CONCEPT 6.3)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.data.models import Grant

from ...conftest import bearer_for

# --- the API -------------------------------------------------------------------------


def test_batch_update(client: TestClient, account_id: str) -> None:
    answer = client.post(
        f"/v1/accounts/{account_id}/messages/batch",
        json={
            "action": "update",
            "ids": ["m0", "nope", "m1", "m0"],
            "changes": {"starred": True},
        },
    )
    assert answer.status_code == 200
    results = answer.json()["results"]
    # One result per id, in order, duplicates once.
    assert [r["id"] for r in results] == ["m0", "nope", "m1"]
    assert results[0]["ok"] is True
    assert results[0]["message"]["starred"] is True
    assert results[1] == {
        "id": "nope",
        "ok": False,
        "message": None,
        "error": {"code": "not_found", "message": "message nope not found"},
    }


@pytest.mark.parametrize(
    "body",
    [
        {"action": "update", "ids": ["m0"]},
        {"action": "update", "ids": [], "changes": {"starred": True}},
        {"action": "update", "ids": ["m"] * 101, "changes": {"starred": True}},
        {"action": "archive", "ids": ["m0"]},
    ],
)
def test_batch_refuses_bad_requests(
    client: TestClient, account_id: str, body: dict[str, object]
) -> None:
    answer = client.post(f"/v1/accounts/{account_id}/messages/batch", json=body)
    assert answer.status_code == 422


def test_batch_needs_the_rights_of_its_action(
    app_client: TestClient, services: Services, account_id: str
) -> None:
    url = f"/v1/accounts/{account_id}/messages/batch"
    delete_all = {"action": "delete", "ids": ["m0", "m1"], "permanent": True}
    writer = bearer_for(services, Grant(accounts=[account_id], allow=["mail.write"]))
    answer = app_client.post(url, json=delete_all, headers=writer)
    assert answer.status_code == 403
    assert "delete_message_permanent" in answer.json()["error"]["message"]

    only_deleting = bearer_for(
        services, Grant(accounts=[account_id], allow=["mail.delete"])
    )
    answer = app_client.post(url, json=delete_all, headers=only_deleting)
    assert answer.status_code == 403
    assert "batch_messages" in answer.json()["error"]["message"]

    both = bearer_for(
        services, Grant(accounts=[account_id], allow=["mail.write", "mail.delete"])
    )
    answer = app_client.post(url, json=delete_all, headers=both)
    assert answer.status_code == 200
    assert [r["ok"] for r in answer.json()["results"]] == [True, True]
