from __future__ import annotations

from fastapi.testclient import TestClient

from benethos_mailbox_api.data.models import Grant, ProviderType
from benethos_mailbox_api.domain import permissions
from benethos_mailbox_api.main import Services

from .conftest import bearer_for, create_account

READ_A = {"accounts": ["acc_a"], "allow": ["mail.read"]}


def test_me_for_the_admin_key(client: TestClient, account_id: str) -> None:
    me = client.get("/v1/me").json()
    assert me["user_id"] == "usr_admin_key"
    assert "list_messages" in me["accounts"][account_id]
    assert "create_account" in me["operations"]
    assert "create_user" in me["operations"]


def test_me_for_a_limited_user(app_client: TestClient, services: Services) -> None:
    a = create_account(services.accounts, ProviderType.MEMORY, "a@example.com").id
    create_account(services.accounts, ProviderType.MEMORY, "b@example.com")
    headers = bearer_for(services, Grant(accounts=[a], allow=["mail.read"]))
    me = app_client.get("/v1/me", headers=headers).json()
    assert me["name"] == "limited"
    assert me["accounts"] == {a: sorted(permissions.GROUPS["mail.read"])}
    assert me["operations"] == []


def test_permission_catalogue(client: TestClient) -> None:
    groups = client.get("/v1/permissions").json()["groups"]
    assert groups["mail.read"] == list(permissions.GROUPS["mail.read"])


def test_user_lifecycle(client: TestClient) -> None:
    created = client.post("/v1/users", json={"name": "dashboard", "grants": [READ_A]})
    assert created.status_code == 201
    user = created.json()
    assert user["id"].startswith("usr_")
    assert client.get(f"/v1/users/{user['id']}").json() == user
    assert [u["id"] for u in client.get("/v1/users").json()] == [user["id"]]

    patched = client.patch(f"/v1/users/{user['id']}", json={"disabled": True}).json()
    assert patched["disabled"] is True
    assert patched["grants"] == [READ_A]

    assert client.delete(f"/v1/users/{user['id']}").status_code == 204
    assert client.get(f"/v1/users/{user['id']}").status_code == 404


def test_token_lifecycle(client: TestClient, app_client: TestClient) -> None:
    user = client.post("/v1/users", json={"name": "script", "grants": [READ_A]}).json()
    created = client.post(f"/v1/users/{user['id']}/tokens", json={"name": "laptop"})
    assert created.status_code == 201
    token = created.json()
    assert token["token"].startswith("mbx_")
    headers = {"Authorization": f"Bearer {token['token']}"}
    assert app_client.get("/v1/me", headers=headers).json()["user_id"] == user["id"]

    listed = client.get(f"/v1/users/{user['id']}/tokens").json()
    assert [t["id"] for t in listed] == [token["id"]]
    assert "token" not in listed[0]
    assert "token_hash" not in listed[0]

    revoked = client.delete(f"/v1/users/{user['id']}/tokens/{token['id']}").json()
    assert revoked["revoked_at"] is not None
    assert app_client.get("/v1/me", headers=headers).status_code == 401


def test_token_of_another_user_is_not_found(client: TestClient) -> None:
    one = client.post("/v1/users", json={"name": "one"}).json()
    two = client.post("/v1/users", json={"name": "two"}).json()
    token = client.post(f"/v1/users/{one['id']}/tokens", json={"name": "t"}).json()
    response = client.delete(f"/v1/users/{two['id']}/tokens/{token['id']}")
    assert response.status_code == 404


def test_deleting_a_user_removes_its_tokens(
    client: TestClient, app_client: TestClient
) -> None:
    user = client.post("/v1/users", json={"name": "gone", "grants": [READ_A]}).json()
    client.post("/v1/users", json={"name": "stays"})
    token = client.post(f"/v1/users/{user['id']}/tokens", json={"name": "t"}).json()
    client.delete(f"/v1/users/{user['id']}")
    headers = {"Authorization": f"Bearer {token['token']}"}
    assert app_client.get("/v1/me", headers=headers).status_code == 401


def test_unknown_right_is_a_bad_request(client: TestClient) -> None:
    response = client.post(
        "/v1/users",
        json={"name": "x", "grants": [{"accounts": ["*"], "allow": ["mail.all"]}]},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "bad_request"


def test_grant_without_accounts_is_a_bad_request(client: TestClient) -> None:
    response = client.post(
        "/v1/users",
        json={"name": "x", "grants": [{"accounts": [], "allow": ["mail.read"]}]},
    )
    assert response.status_code == 400


def test_unknown_role_is_a_bad_request(client: TestClient) -> None:
    response = client.post("/v1/users", json={"name": "x", "roles": ["ghost"]})
    assert response.status_code == 400


def test_role_lifecycle(client: TestClient) -> None:
    role = {"id": "reader", "grants": [{"accounts": ["*"], "allow": ["mail.read"]}]}
    assert client.post("/v1/roles", json=role).json() == role
    assert client.post("/v1/roles", json=role).status_code == 409
    assert client.get("/v1/roles/reader").json() == role
    assert [r["id"] for r in client.get("/v1/roles").json()] == ["reader"]

    replaced = client.put("/v1/roles/reader", json={"grants": [READ_A]}).json()
    assert replaced["grants"] == [READ_A]

    user = client.post("/v1/users", json={"name": "u", "roles": ["reader"]}).json()
    assert client.delete("/v1/roles/reader").status_code == 409
    client.patch(f"/v1/users/{user['id']}", json={"roles": []})
    assert client.delete("/v1/roles/reader").status_code == 204


# --- no escalation ---------------------------------------------------------


def _manager(services: Services, *extra: Grant) -> dict[str, str]:
    """A user who may manage users and read mail on acc_a only."""
    return bearer_for(
        services,
        Grant(accounts=["*"], allow=["users.manage"]),
        Grant(accounts=["acc_a"], allow=["mail.read"]),
        *extra,
    )


def test_cannot_grant_what_the_caller_lacks(
    app_client: TestClient, services: Services
) -> None:
    headers = _manager(services)
    ok = app_client.post(
        "/v1/users", json={"name": "ok", "grants": [READ_A]}, headers=headers
    )
    assert ok.status_code == 201
    too_much = app_client.post(
        "/v1/users",
        json={"name": "x", "grants": [{"accounts": ["*"], "allow": ["mail.read"]}]},
        headers=headers,
    )
    assert too_much.status_code == 403


def test_cannot_escalate_through_a_role(
    app_client: TestClient, client: TestClient, services: Services
) -> None:
    client.post(
        "/v1/roles",
        json={"id": "all", "grants": [{"accounts": ["*"], "allow": ["admin"]}]},
    )
    headers = _manager(services)
    response = app_client.post(
        "/v1/users", json={"name": "x", "roles": ["all"]}, headers=headers
    )
    assert response.status_code == 403


def test_cannot_manage_a_stronger_user(
    app_client: TestClient, client: TestClient, services: Services
) -> None:
    strong = client.post(
        "/v1/users",
        json={"name": "s", "grants": [{"accounts": ["*"], "allow": ["admin"]}]},
    ).json()
    headers = _manager(services)
    assert (
        app_client.patch(
            f"/v1/users/{strong['id']}", json={"disabled": True}, headers=headers
        ).status_code
        == 403
    )
    assert (
        app_client.post(
            f"/v1/users/{strong['id']}/tokens", json={"name": "t"}, headers=headers
        ).status_code
        == 403
    )
    assert (
        app_client.delete(f"/v1/users/{strong['id']}", headers=headers).status_code
        == 403
    )


def test_a_user_cannot_delete_itself(
    app_client: TestClient, services: Services
) -> None:
    headers = _manager(services)
    me = app_client.get("/v1/me", headers=headers).json()
    response = app_client.delete(f"/v1/users/{me['user_id']}", headers=headers)
    assert response.status_code == 409


def test_without_users_manage_nothing_is_listed(
    app_client: TestClient, services: Services
) -> None:
    headers = bearer_for(services, Grant(accounts=["*"], allow=["mail.read"]))
    assert app_client.get("/v1/users", headers=headers).status_code == 403
    assert app_client.get("/v1/roles", headers=headers).status_code == 403
    assert app_client.get("/v1/me", headers=headers).status_code == 200
