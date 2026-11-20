"""Deleting a message: into the trash, or for good (CONCEPT 6.3, 7.5)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.data.models import Grant

from ...conftest import bearer_for

# --- the API and its rights ------------------------------------------------------


def test_delete_without_a_trash_folder(client: TestClient, account_id: str) -> None:
    # The memory account has an inbox and a sent folder only: it lacks
    # the trash (UNIFORM R2).
    answer = client.delete(f"/v1/accounts/{account_id}/messages/m0")
    assert answer.status_code == 501
    assert answer.json()["error"]["code"] == "not_supported"


def test_deleting_for_good_is_its_own_right(
    app_client: TestClient, services: Services, account_id: str
) -> None:
    url = f"/v1/accounts/{account_id}/messages/m1"
    writer = bearer_for(
        services, Grant(accounts=[account_id], allow=["mail.read", "mail.write"])
    )
    answer = app_client.delete(url, params={"permanent": True}, headers=writer)
    assert answer.status_code == 403
    assert "delete_message_permanent" in answer.json()["error"]["message"]

    deleter = bearer_for(
        services, Grant(accounts=[account_id], allow=["mail.read", "mail.delete"])
    )
    answer = app_client.delete(url, params={"permanent": True}, headers=deleter)
    assert answer.status_code == 204
    assert app_client.get(url, headers=deleter).status_code == 404
