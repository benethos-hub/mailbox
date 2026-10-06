from __future__ import annotations

import secrets
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service.common.clock import utc_now
from benethos_mailbox_service.data.models import Grant, ProviderType
from benethos_mailbox_service.domain.rights import permissions
from benethos_mailbox_service.domain.rights.access import ADMIN_SERVICE, Access
from benethos_mailbox_service.main import Services

from ...conftest import ADMIN, bearer_for, browser_user, create_account
from ...ui_helpers import sign_in

READ_A = {"accounts": ["acc_a"], "allow": ["mail.read"]}
# As the API answers it: constraints not set are null.
READ_A_OUT = {
    **READ_A,
    "recipients": None,
    "max_sends_per_day": None,
    "folders": None,
    "expires_at": None,
}


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
            "sending": [],
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
    assert [
        (s.recipients, s.max_sends_per_day, s.sends_left) for s in account.sending
    ] == [(["*@a.org"], None, None), (None, 2, 2)]


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


def test_a_manager_of_one_account_manages_itself(
    app_client: TestClient, services: Services
) -> None:
    own = Grant(accounts=["acc_a"], allow=["mail.read", "accounts.manage"])
    headers = bearer_for(services, own, service=["users.manage"])
    me = app_client.get("/v1/me", headers=headers).json()
    renamed = app_client.patch(
        f"/v1/users/{me['user_id']}", json={"name": "renamed"}, headers=headers
    )
    assert renamed.status_code == 200
    made = app_client.post(
        "/v1/users",
        json={
            "name": "like-me",
            "service": ["users.manage"],
            "grants": [own.model_dump()],
        },
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
        "service": [],
        "grants": [
            {
                "accounts": ["*"],
                "allow": ["mail.read"],
                "recipients": None,
                "max_sends_per_day": None,
                "folders": None,
                "expires_at": None,
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


def test_the_list_filters(client: TestClient) -> None:
    client.post("/v1/roles", json={"id": "reader", "grants": [READ_A]})
    client.post("/v1/users", json={"name": "Anna", "roles": ["reader"]})
    client.post("/v1/users", json={"name": "Hanna", "ui_sign_in": True})
    bob = client.post("/v1/users", json={"name": "Bob"}).json()["id"]
    client.patch(f"/v1/users/{bob}", json={"disabled": True})

    def names(**params: str) -> list[str]:
        answer = client.get("/v1/users", params=params)
        assert answer.status_code == 200, answer.text
        return sorted(
            u["name"] for u in answer.json() if not u["name"].startswith("api-")
        )

    assert names(name="ANNA") == ["Anna", "Hanna"]
    assert names(role="reader") == ["Anna"]
    assert names(disabled="true") == ["Bob"]
    assert names(ui_sign_in="true") == ["Hanna"]
    assert names(ui_sign_in="false", disabled="false", name="a") == ["Anna"]
    assert client.get("/v1/users", params={"disabled": "maybe"}).status_code == 422


def test_a_user_names_how_it_signs_in_to_the_ui(
    client: TestClient, app_client: TestClient
) -> None:
    def state(user: dict[str, object]) -> tuple[object, ...]:
        return (user["has_password"], user["must_change"], user["last_sign_in_at"])

    made = client.post("/v1/users", json={"name": "Anna", "ui_sign_in": True})
    anna = made.json()["id"]
    assert state(made.json()) == (False, False, None)
    url = f"/v1/users/{anna}/password"
    password = client.post(url, json={}).json()["password"]
    assert state(client.get(f"/v1/users/{anna}").json()) == (True, True, None)
    sign_in(app_client, "Anna", password)
    [listed] = client.get("/v1/users", params={"name": "Anna"}).json()
    has_password, must_change, last = state(listed)
    assert (has_password, must_change) == (True, True)
    assert isinstance(last, str) and last.endswith("Z")
    assert "hash" not in str(listed) and password not in str(listed)


def test_nobody_disables_itself_or_takes_its_own_ui_sign_in(
    client: TestClient,
) -> None:
    me = client.get("/v1/me").json()
    for change in ({"disabled": True}, {"ui_sign_in": False}):
        refused = client.patch(f"/v1/users/{me['user_id']}", json=change)
        assert refused.status_code == 409, change
    assert client.get("/v1/me").status_code == 200


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
    services.users.create_role(ADMIN, "admins", [], list(ADMIN_SERVICE))
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
        "start_oauth",
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
