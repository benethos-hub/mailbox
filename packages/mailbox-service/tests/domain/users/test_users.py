from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service.data.models import Grant, ProviderType
from benethos_mailbox_service.domain.rights import permissions
from benethos_mailbox_service.domain.rights.access import Access
from benethos_mailbox_service.main import Services

from ...conftest import bearer_for, create_account

READ_A = {"accounts": ["acc_a"], "allow": ["mail.read"]}
# As the API answers it: constraints not set are null.
READ_A_OUT = {**READ_A, "recipients": None, "max_sends_per_day": None}


def test_me_for_an_admin(client: TestClient, account_id: str) -> None:
    me = client.get("/v1/me").json()
    assert me["user_id"].startswith("usr_") and me["name"].startswith("api-admin-")
    [account] = me["accounts"]
    assert (account["id"], account["email"]) == (account_id, "me@example.com")
    assert "list_messages" in account["operations"]
    assert "create_account" in me["operations"]
    assert "create_user" in me["operations"]


def test_me_for_a_limited_user(app_client: TestClient, services: Services) -> None:
    a = create_account(services.accounts, ProviderType.MEMORY, "a@example.com").id
    create_account(services.accounts, ProviderType.MEMORY, "b@example.com")
    headers = bearer_for(services, Grant(accounts=[a], allow=["mail.read"]))
    me = app_client.get("/v1/me", headers=headers).json()
    assert me["name"].startswith("limited-")
    assert me["accounts"] == [
        {
            "id": a,
            "email": "a@example.com",
            "display_name": None,
            "operations": sorted(permissions.GROUPS["mail.read"]),
            "warnings": [],
        }
    ]
    assert me["operations"] == []


def warnings_of(
    app_client: TestClient, services: Services, *grants: Grant
) -> list[str]:
    headers = bearer_for(services, *grants)
    [account] = app_client.get("/v1/me", headers=headers).json()["accounts"]
    return list(account["warnings"])


def test_me_warns_who_may_read_and_send_anywhere(
    app_client: TestClient, services: Services, account_id: str
) -> None:
    read, send = ["mail.read"], ["send"]
    assert warnings_of(
        app_client, services, Grant(accounts=[account_id], allow=[*read, *send])
    ) == ["read_and_send_anywhere"]
    # A limit narrows how often, not to whom.
    assert warnings_of(
        app_client,
        services,
        Grant(accounts=[account_id], allow=[*read, *send], max_sends_per_day=3),
    ) == ["read_and_send_anywhere"]
    # One grant with recipients "*" is as wide as none.
    assert warnings_of(
        app_client,
        services,
        Grant(accounts=[account_id], allow=read),
        Grant(accounts=[account_id], allow=send, recipients=["*"]),
    ) == ["read_and_send_anywhere"]


def test_no_warning_when_sending_is_narrowed_or_blind(
    app_client: TestClient, services: Services, account_id: str
) -> None:
    narrowed = Grant(
        accounts=[account_id], allow=["mail.read", "send"], recipients=["*@a.org"]
    )
    assert warnings_of(app_client, services, narrowed) == []
    blind = Grant(accounts=[account_id], allow=["send", "drafts"])
    assert warnings_of(app_client, services, blind) == []


def test_me_lists_the_limits_of_every_sending_grant(
    services: Services, account_id: str
) -> None:
    access = Access(
        "usr_x",
        "x",
        [
            Grant(accounts=[account_id], allow=["send_draft"], recipients=["*@a.org"]),
            Grant(accounts=[account_id], allow=["send"], max_sends_per_day=2),
        ],
    )
    [account] = services.users.me(access).accounts
    assert [(s.recipients, s.max_per_day) for s in account.sending] == [
        (("*@a.org",), None),
        (None, 2),
    ]


def test_an_admin_is_warned(client: TestClient, account_id: str) -> None:
    [account] = client.get("/v1/me").json()["accounts"]
    assert account["warnings"] == ["read_and_send_anywhere"]


def test_permission_catalogue(client: TestClient) -> None:
    groups = client.get("/v1/permissions").json()["groups"]
    assert groups["mail.read"] == list(permissions.GROUPS["mail.read"])


def test_user_lifecycle(client: TestClient) -> None:
    created = client.post("/v1/users", json={"name": "dashboard", "grants": [READ_A]})
    assert created.status_code == 201
    user = created.json()
    assert user["id"].startswith("usr_")
    assert client.get(f"/v1/users/{user['id']}").json() == user
    assert user["id"] in [u["id"] for u in client.get("/v1/users").json()]

    # An API user unless said otherwise.
    assert user["ui_sign_in"] is False
    patched = client.patch(f"/v1/users/{user['id']}", json={"disabled": True}).json()
    assert patched["disabled"] is True
    assert patched["grants"] == [READ_A_OUT]
    switched = client.patch(f"/v1/users/{user['id']}", json={"ui_sign_in": True})
    assert switched.json()["ui_sign_in"] is True

    assert client.delete(f"/v1/users/{user['id']}").status_code == 204
    assert client.get(f"/v1/users/{user['id']}").status_code == 404


def test_a_user_with_a_renamed_right_stays_manageable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    grant = {"accounts": ["*"], "allow": ["mail.read", "drafts"]}
    user = client.post("/v1/users", json={"name": "old", "grants": [grant]}).json()
    # A release renames the group: the stored grant names a right that is gone.
    monkeypatch.delitem(permissions.GROUPS, "drafts")
    renamed = client.patch(f"/v1/users/{user['id']}", json={"name": "renewed"})
    assert renamed.status_code == 200
    assert (
        client.post(f"/v1/users/{user['id']}/tokens", json={"name": "t"}).status_code
        == 201
    )
    assert client.delete(f"/v1/users/{user['id']}").status_code == 204


def test_an_admin_of_one_account_manages_itself(
    app_client: TestClient, services: Services
) -> None:
    own = Grant(accounts=["acc_a"], allow=["admin"])
    headers = bearer_for(services, own)
    me = app_client.get("/v1/me", headers=headers).json()
    renamed = app_client.patch(
        f"/v1/users/{me['user_id']}", json={"name": "renamed"}, headers=headers
    )
    assert renamed.status_code == 200
    made = app_client.post(
        "/v1/users",
        json={"name": "like-me", "grants": [own.model_dump()]},
        headers=headers,
    )
    assert made.status_code == 201


def test_a_token_expiry_needs_a_time_zone(client: TestClient) -> None:
    user = client.post("/v1/users", json={"name": "naive"}).json()
    url = f"/v1/users/{user['id']}/tokens"
    naive = client.post(url, json={"name": "t", "expires_at": "2099-01-01T00:00:00"})
    assert naive.status_code == 422
    aware = client.post(url, json={"name": "t", "expires_at": "2099-01-01T00:00:00Z"})
    assert aware.status_code == 201


async def test_a_password_through_the_api(
    client: TestClient, services: Services
) -> None:
    user = client.post("/v1/users", json={"name": "person", "ui_sign_in": True}).json()
    url = f"/v1/users/{user['id']}/password"
    made = client.post(url, json={})
    assert made.status_code == 200
    one_time = made.json()["password"]
    signed = await services.auth.sign_in("person", one_time, source="test")
    assert signed.must_change
    chosen = client.post(url, json={"password": "a passphrase chosen for them"})
    assert chosen.json() == {"password": None, "must_change": True}
    await services.auth.sign_in("person", "a passphrase chosen for them", source="t")
    # An API user has no password, and nobody sets its own this way.
    api_user = client.post("/v1/users", json={"name": "script"}).json()
    refused = client.post(f"/v1/users/{api_user['id']}/password", json={})
    assert refused.status_code == 409
    me = client.get("/v1/me").json()["user_id"]
    assert client.post(f"/v1/users/{me}/password", json={}).status_code == 409


async def test_a_name_is_kept_without_the_spaces_around_it(
    client: TestClient, services: Services
) -> None:
    made = client.post("/v1/users", json={"name": " Admin2 ", "ui_sign_in": True})
    assert made.json()["name"] == "Admin2"
    again = client.post("/v1/users", json={"name": "admin2"})
    assert again.status_code == 409
    password = client.post(f"/v1/users/{made.json()['id']}/password", json={})
    await services.auth.sign_in("Admin2", password.json()["password"], source="t")
    renamed = client.patch(f"/v1/users/{made.json()['id']}", json={"name": " B "})
    assert renamed.json()["name"] == "B"
    long = client.post("/v1/users", json={"name": "x" * 201})
    assert long.status_code == 400
    role = client.post("/v1/roles", json={"id": " readers ", "grants": []})
    assert role.json()["id"] == "readers"


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
    stored = {
        "id": "reader",
        "grants": [
            {
                "accounts": ["*"],
                "allow": ["mail.read"],
                "recipients": None,
                "max_sends_per_day": None,
            }
        ],
    }
    assert client.post("/v1/roles", json=role).json() == stored
    assert client.post("/v1/roles", json=role).status_code == 409
    assert client.get("/v1/roles/reader").json() == stored
    assert [r["id"] for r in client.get("/v1/roles").json()] == ["reader"]

    replaced = client.put("/v1/roles/reader", json={"grants": [READ_A]}).json()
    assert replaced["grants"] == [READ_A_OUT]

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


def test_cannot_change_the_role_of_a_stronger_user(
    app_client: TestClient, client: TestClient, services: Services
) -> None:
    client.post("/v1/roles", json={"id": "readers", "grants": [READ_A]})
    client.post(
        "/v1/users",
        json={
            "name": "strong",
            "roles": ["readers"],
            "grants": [{"accounts": ["*"], "allow": ["admin"]}],
        },
    )
    headers = _manager(services)
    # The manager covers the role, but not the admin who holds it.
    shrunk = app_client.put("/v1/roles/readers", json={"grants": []}, headers=headers)
    assert shrunk.status_code == 403
    assert client.get("/v1/roles/readers").json()["grants"] != []


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
        app_client.get(f"/v1/users/{strong['id']}/tokens", headers=headers).status_code
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


def test_nobody_disables_itself_or_takes_its_own_ui_sign_in(
    client: TestClient,
) -> None:
    me = client.get("/v1/me").json()
    for change in ({"disabled": True}, {"ui_sign_in": False}):
        refused = client.patch(f"/v1/users/{me['user_id']}", json=change)
        assert refused.status_code == 409, change
    assert client.get("/v1/me").status_code == 200
