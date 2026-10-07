"""Users through the API: no escalation, the last administrator, rights
of the service, sending limits in /v1/me, grants that expire."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.common.clock import utc_now
from benethos_mailbox_service.data.models import Grant
from benethos_mailbox_service.domain.rights import permissions
from benethos_mailbox_service.domain.rights.access import ADMIN_SERVICE

from ...conftest import ADMIN, bearer_for, browser_user
from .test_users import READ_A

# --- no escalation ---------------------------------------------------------


def _manager(services: Services, *extra: Grant) -> dict[str, str]:
    """A user who may manage users and read mail on acc_a only."""
    return bearer_for(
        services,
        Grant(accounts=["acc_a"], allow=["mail.read"]),
        *extra,
        service=["users.manage"],
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
        json={"id": "all", "service": ["admin"]},
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
            "service": ["admin"],
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
        json={"name": "s", "service": ["admin"]},
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


# --- the last administrator stays (PERMISSIONS.md 8.3) ----------------------------


def _ui_admin(services: Services, *, role: str | None = None) -> str:
    """A user who signs in to the UI with ``admin``, directly or by a role."""
    if role is None:
        name, _ = browser_user(services, service=list(ADMIN_SERVICE), name="boss")
    else:
        name, _ = browser_user(services, roles=[role], name="boss")
    found = services.auth.user_named(name)
    assert found is not None
    return found.id


@pytest.mark.parametrize(
    "change",
    [
        {"disabled": True},
        {"ui_sign_in": False},
        {"service": ["users.manage"]},
    ],
)
def test_the_last_ui_administrator_cannot_be_changed_away(
    client: TestClient, services: Services, change: dict[str, object]
) -> None:
    boss = _ui_admin(services)
    refused = client.patch(f"/v1/users/{boss}", json=change)
    assert refused.status_code == 409, change
    assert "administrator" in refused.json()["error"]["message"]


def test_the_last_ui_administrator_cannot_be_deleted(
    client: TestClient, services: Services
) -> None:
    boss = _ui_admin(services)
    assert client.delete(f"/v1/users/{boss}").status_code == 409
    assert services.users.get_user(ADMIN, boss).id == boss


def test_a_second_ui_administrator_may_go(
    client: TestClient, services: Services
) -> None:
    boss = _ui_admin(services)
    browser_user(services, service=list(ADMIN_SERVICE), name="deputy")
    assert client.patch(f"/v1/users/{boss}", json={"disabled": True}).status_code == 200


def test_a_role_cannot_take_admin_from_the_last_ui_administrator(
    client: TestClient, services: Services
) -> None:
    services.roles.create_role(ADMIN, "admins", [], list(ADMIN_SERVICE))
    _ui_admin(services, role="admins")
    refused = client.put(
        "/v1/roles/admins",
        json={"grants": [{"accounts": ["*"], "allow": ["mail.read"]}]},
    )
    assert refused.status_code == 409


def test_without_a_ui_administrator_nothing_is_held_back(
    client: TestClient, services: Services
) -> None:
    """An API admin alone is no administrator of the UI: no change waits
    for one."""
    name, _ = browser_user(services, Grant(accounts=["*"], allow=["mail.read"]))
    user = services.auth.user_named(name)
    assert user is not None
    assert client.delete(f"/v1/users/{user.id}").status_code == 204


# --- rights of the service (PERMISSIONS.md 8.1, 8.2) -------------------------------


@pytest.mark.parametrize("name", ["admin", "users.manage", "create_account"])
def test_a_right_of_the_service_in_a_grant_answers_400(
    client: TestClient, name: str
) -> None:
    grant = {"accounts": ["*"], "allow": ["mail.read", name]}
    for answer in (
        client.post("/v1/users", json={"name": "x", "grants": [grant]}),
        client.post("/v1/roles", json={"id": "x", "grants": [grant]}),
    ):
        assert answer.status_code == 400
        assert "name it in service" in answer.json()["error"]["message"]


def test_a_right_on_accounts_in_service_answers_400(client: TestClient) -> None:
    answer = client.post("/v1/users", json={"name": "x", "service": ["mail.read"]})
    assert answer.status_code == 400
    assert "name it in a grant" in answer.json()["error"]["message"]


def test_service_rights_of_a_user_and_a_role(client: TestClient) -> None:
    role = client.post(
        "/v1/roles", json={"id": "hooks", "service": ["webhooks.manage"]}
    ).json()
    assert role["service"] == ["webhooks.manage"]
    user = client.post(
        "/v1/users",
        json={"name": "u", "roles": ["hooks"], "service": ["users.read"]},
    ).json()
    assert user["service"] == ["users.read"]
    token = client.post(f"/v1/users/{user['id']}/tokens", json={"name": "t"}).json()
    me = client.get(
        "/v1/me", headers={"Authorization": f"Bearer {token['token']}"}
    ).json()
    assert "create_webhook" in me["operations"] and "list_users" in me["operations"]
    assert "create_user" not in me["operations"]
    changed = client.patch(f"/v1/users/{user['id']}", json={"service": []}).json()
    assert changed["service"] == []
    replaced = client.put("/v1/roles/hooks", json={}).json()
    assert replaced["service"] == []


def test_users_read_sees_users_and_changes_none(
    app_client: TestClient, client: TestClient, services: Services
) -> None:
    other = client.post("/v1/users", json={"name": "other"}).json()
    reader = TestClient(
        app_client.app, headers=bearer_for(services, service=["users.read"])
    )
    assert reader.get("/v1/users").status_code == 200
    assert reader.get(f"/v1/users/{other['id']}").status_code == 200
    assert reader.get(f"/v1/users/{other['id']}/tokens").status_code == 200
    assert reader.get("/v1/roles").status_code == 200
    assert reader.post("/v1/users", json={"name": "x"}).status_code == 403
    made = reader.post(f"/v1/users/{other['id']}/tokens", json={"name": "t"})
    assert made.status_code == 403


def test_the_catalogue_names_the_groups_of_the_service(client: TestClient) -> None:
    catalogue = client.get("/v1/permissions").json()
    assert catalogue["service"] == list(permissions.SERVICE_GROUPS)
    assert catalogue["groups"]["accounts.connect"] == [
        "discover_account",
        "start_device_oauth",
        "poll_device_oauth",
        "create_account",
    ]


# --- sending limits in /v1/me (PERMISSIONS.md 8.8) ---------------------------------


def test_me_names_the_sends_left(
    app_client: TestClient, services: Services, account_id: str
) -> None:
    limited = Grant(
        accounts=[account_id],
        allow=["send"],
        recipients=["*@example.com"],
        max_sends_per_day=2,
    )
    headers = bearer_for(services, limited)
    mail = {"to": [{"email": "bob@example.com"}], "subject": "Hi", "text": "x"}
    sent = app_client.post(
        f"/v1/accounts/{account_id}/send", json=mail, headers=headers
    )
    assert sent.status_code == 200
    [account] = app_client.get("/v1/me", headers=headers).json()["accounts"]
    assert account["sending"] == [
        {"recipients": ["*@example.com"], "max_sends_per_day": 2, "sends_left": 1}
    ]


# --- a grant can expire (PERMISSIONS.md 8.4) ---------------------------------------


def test_an_expired_grant_grants_nothing(
    app_client: TestClient, client: TestClient, services: Services, account_id: str
) -> None:
    past = (utc_now() - timedelta(minutes=1)).isoformat()
    future = (utc_now() + timedelta(days=7)).isoformat()
    made = client.post(
        "/v1/users",
        json={
            "name": "contractor",
            "grants": [
                {"accounts": [account_id], "allow": ["mail.read"], "expires_at": past},
                {"accounts": [account_id], "allow": ["drafts"], "expires_at": future},
            ],
        },
    ).json()
    assert made["grants"][0]["expires_at"] is not None
    token = client.post(f"/v1/users/{made['id']}/tokens", json={"name": "t"}).json()
    headers = {"Authorization": f"Bearer {token['token']}"}
    [account] = app_client.get("/v1/me", headers=headers).json()["accounts"]
    assert "create_draft" in account["operations"]
    assert "list_messages" not in account["operations"]
    messages = app_client.get(f"/v1/accounts/{account_id}/messages", headers=headers)
    assert messages.status_code == 403


def test_an_expiry_needs_a_time_zone(client: TestClient) -> None:
    grant = {
        "accounts": ["*"],
        "allow": ["mail.read"],
        "expires_at": "2099-01-01T00:00",
    }
    assert (
        client.post("/v1/users", json={"name": "x", "grants": [grant]}).status_code
        == 422
    )


def test_a_right_held_for_a_while_is_handed_out_for_no_longer(
    app_client: TestClient, services: Services
) -> None:
    """A contractor with users.manage and a grant for a week cannot give
    anyone that grant for longer, nor without an end."""
    week = utc_now() + timedelta(days=7)
    headers = bearer_for(
        services,
        Grant(accounts=["acc_a"], allow=["mail.read"], expires_at=week),
        service=["users.manage"],
    )

    def made(expires_at: datetime | None) -> int:
        grant = {
            "accounts": ["acc_a"],
            "allow": ["mail.read"],
            "expires_at": expires_at.isoformat() if expires_at else None,
        }
        return app_client.post(
            "/v1/users",
            json={"name": f"u{secrets.token_hex(3)}", "grants": [grant]},
            headers=headers,
        ).status_code

    assert made(None) == 403
    assert made(week + timedelta(days=1)) == 403
    assert made(week) == 201
    assert made(week - timedelta(days=1)) == 201
