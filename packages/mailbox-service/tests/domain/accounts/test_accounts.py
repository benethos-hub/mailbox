from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service.data.models import Grant
from benethos_mailbox_service.main import Services

from ...conftest import ADMIN, bearer_for


def test_create_list_get_delete(client: TestClient) -> None:
    created = client.post(
        "/v1/accounts", json={"provider": "memory", "email": "a@example.com"}
    )
    assert created.status_code == 201
    account = created.json()
    assert account["id"].startswith("acc_")
    assert account["status"] == "connected"

    assert [a["id"] for a in client.get("/v1/accounts").json()["items"]] == [
        account["id"]
    ]
    assert client.get(f"/v1/accounts/{account['id']}").json() == account

    assert client.delete(f"/v1/accounts/{account['id']}").status_code == 204
    assert client.get(f"/v1/accounts/{account['id']}").status_code == 404


def test_the_list_filters(client: TestClient) -> None:
    for email in ("anna@example.com", "bob@example.org"):
        client.post("/v1/accounts", json={"provider": "memory", "email": email})

    def emails(**params: str) -> list[str]:
        answer = client.get("/v1/accounts", params=params)
        assert answer.status_code == 200, answer.text
        return sorted(a["email"] for a in answer.json()["items"])

    assert emails() == ["anna@example.com", "bob@example.org"]
    assert emails(address="EXAMPLE.ORG") == ["bob@example.org"]
    assert emails(provider="memory", status="connected", address="anna") == [
        "anna@example.com"
    ]
    assert emails(status="needs_reauth") == []
    assert emails(provider="imap") == []
    for wrong in ({"provider": "carrier pigeon"}, {"status": "asleep"}):
        assert client.get("/v1/accounts", params=wrong).status_code == 422


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
    listed = client.get("/v1/accounts").json()["items"]
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


# --- a request that fails validation does not come back --------------------------


def test_a_422_does_not_echo_the_request(client: TestClient) -> None:
    """FastAPI's default 422 repeats the offending input, which here may be
    a provider password. Only the location and the message come back."""
    response = client.post(
        "/v1/accounts",
        json={"provider": "imap", "credentials": {"password": "S3cretPW"}},
    )
    assert response.status_code == 422
    assert "S3cretPW" not in response.text
    [error] = response.json()["detail"]
    assert set(error) == {"type", "loc", "msg"}
    assert error["loc"] == ["body", "email"]
    assert error["type"] == "missing"


# --- whoever connects an account (PERMISSIONS.md 8.1) -----------------------------


def test_the_connector_gets_accounts_manage_on_what_it_connected(
    app_client: TestClient, services: Services
) -> None:
    """It can verify and remove what it connected, and read nothing."""
    connector = TestClient(
        app_client.app, headers=bearer_for(services, service=["accounts.connect"])
    )
    created = connector.post(
        "/v1/accounts", json={"provider": "memory", "email": "new@example.org"}
    )
    assert created.status_code == 201
    account_id = created.json()["id"]
    [account] = connector.get("/v1/me").json()["accounts"]
    assert account["id"] == account_id
    assert account["operations"] == [
        "delete_account",
        "update_account",
        "verify_account",
    ]
    assert connector.get(f"/v1/accounts/{account_id}/messages").status_code == 403
    assert connector.delete(f"/v1/accounts/{account_id}").status_code == 204


def test_a_connector_that_manages_every_account_gets_no_grant(
    app_client: TestClient, services: Services
) -> None:
    every = Grant(accounts=["*"], allow=["accounts.manage"])
    headers = bearer_for(services, every, service=["accounts.connect"])
    connector = TestClient(app_client.app, headers=headers)
    connector.post(
        "/v1/accounts", json={"provider": "memory", "email": "n@example.org"}
    )
    me = connector.get("/v1/me").json()
    assert services.users.get_user(ADMIN, me["user_id"]).grants == [every]


def test_the_list_pages_by_address(client: TestClient) -> None:
    for email in ("carl@example.com", "Anna@example.com", "bob@example.org"):
        client.post("/v1/accounts", json={"provider": "memory", "email": email})
    first = client.get("/v1/accounts", params={"limit": 2}).json()
    assert [a["email"] for a in first["items"]] == [
        "Anna@example.com",
        "bob@example.org",
    ]
    rest = client.get(
        "/v1/accounts", params={"limit": 2, "cursor": first["next_cursor"]}
    ).json()
    assert [a["email"] for a in rest["items"]] == ["carl@example.com"]
    assert rest["next_cursor"] is None

    narrowed = client.get("/v1/accounts", params={"limit": 1, "address": "example.com"})
    assert [a["email"] for a in narrowed.json()["items"]] == ["Anna@example.com"]
    assert client.get("/v1/accounts", params={"cursor": "nope"}).status_code == 400
    assert client.get("/v1/accounts", params={"limit": 0}).status_code == 422
