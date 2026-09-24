from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def test_create_list_get_delete(client: TestClient) -> None:
    created = client.post(
        "/v1/accounts", json={"provider": "memory", "email": "a@example.com"}
    )
    assert created.status_code == 201
    account = created.json()
    assert account["id"].startswith("acc_")
    assert account["status"] == "connected"

    assert [a["id"] for a in client.get("/v1/accounts").json()] == [account["id"]]
    assert client.get(f"/v1/accounts/{account['id']}").json() == account

    assert client.delete(f"/v1/accounts/{account['id']}").status_code == 204
    assert client.get(f"/v1/accounts/{account['id']}").status_code == 404


def test_unknown_account_has_error_envelope(client: TestClient) -> None:
    response = client.get("/v1/accounts/acc_missing")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_unimplemented_provider_is_501(client: TestClient) -> None:
    response = client.post(
        "/v1/accounts", json={"provider": "gmail", "email": "a@example.com"}
    )
    assert response.status_code == 501
    assert response.json()["error"]["code"] == "not_supported"


# --- settings are shown, secrets never -------------------------------------------


def test_the_settings_come_back(client: TestClient) -> None:
    created = client.post(
        "/v1/accounts",
        json={
            "provider": "memory",
            "email": "s@example.org",
            "settings": {"host": "imap.example.org", "port": 993},
        },
    ).json()
    assert created["settings"] == {"host": "imap.example.org", "port": 993}
    listed = client.get("/v1/accounts").json()
    assert [a["settings"] for a in listed if a["id"] == created["id"]] == [
        {"host": "imap.example.org", "port": 993}
    ]


@pytest.mark.parametrize(
    "key", ["password", "smtp_password", "Client-Secret", "api_key", "refresh_token"]
)
def test_a_secret_in_the_settings_is_refused(client: TestClient, key: str) -> None:
    body = {"provider": "memory", "email": "s@example.org", "settings": {key: "x"}}
    answer = client.post("/v1/accounts", json=body)
    assert answer.status_code == 400
    assert "credentials" in answer.json()["error"]["message"]


def test_a_secret_in_changed_settings_is_refused(
    client: TestClient, account_id: str
) -> None:
    answer = client.patch(
        f"/v1/accounts/{account_id}", json={"settings": {"password": "x"}}
    )
    assert answer.status_code == 400
