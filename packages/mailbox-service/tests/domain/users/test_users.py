"""Users, tokens and roles through the API, and /v1/me."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.data.models import Grant, ProviderType
from benethos_mailbox_service.domain.rights import permissions
from benethos_mailbox_service.domain.rights.access import Access

from ...conftest import bearer_for, create_account
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
            "capabilities": [
                "drafts",
                "flags",
                "folders",
                "search",
                "send",
                "stable_ids",
            ],
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
    assert user["id"] in [u["id"] for u in client.get("/v1/users").json()["items"]]

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

    gone = client.delete(f"/v1/users/{user['id']}/tokens/{token['id']}")
    assert gone.status_code == 204
    assert app_client.get("/v1/me", headers=headers).status_code == 401
    # The token stays listed, with the time it was revoked.
    [revoked] = client.get(f"/v1/users/{user['id']}/tokens").json()
    assert revoked["revoked_at"] is not None


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
            u["name"]
            for u in answer.json()["items"]
            if not u["name"].startswith("api-")
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
    [listed] = client.get("/v1/users", params={"name": "Anna"}).json()["items"]
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


def test_the_list_pages_by_name(client: TestClient) -> None:
    for name in ("carl", "Anna", "bob"):
        client.post("/v1/users", json={"name": name})

    def names(**params: str | int) -> tuple[list[str], str | None]:
        # Not "b": the admin of the tests is named api-admin-N.
        answer = client.get("/v1/users", params={"name": "a", **params})
        assert answer.status_code == 200, answer.text
        body = answer.json()
        assert all("has_password" in u for u in body["items"])  # UserInfo
        found = [u["name"] for u in body["items"]]
        return ["admin" if n.startswith("api-") else n for n in found], body[
            "next_cursor"
        ]

    first, cursor = names(limit=2)
    assert (first, cursor is not None) == (["Anna", "admin"], True)
    assert names(limit=2, cursor=str(cursor)) == (["carl"], None)
    assert client.get("/v1/users", params={"cursor": "nope"}).status_code == 400


def test_several_tokens_are_revoked_at_once_or_none(services: Services) -> None:
    from benethos_mailbox_service.errors import BadRequestError, NotFoundError

    from ...conftest import ADMIN

    user = services.users.create_user(ADMIN, "bot", [], [])
    other = services.users.create_user(ADMIN, "other", [], [])
    one = services.auth.issue_token(user.id, "one").token
    two = services.auth.issue_token(user.id, "two").token
    foreign = services.auth.issue_token(other.id, "foreign").token
    with pytest.raises(NotFoundError):
        services.tokens.revoke_tokens(ADMIN, user.id, [one.id, foreign.id])
    listed = services.tokens.list_tokens(ADMIN, user.id)
    assert all(t.revoked_at is None for t in listed)
    with pytest.raises(BadRequestError):
        services.tokens.revoke_tokens(ADMIN, user.id, [])
    revoked = services.tokens.revoke_tokens(ADMIN, user.id, [one.id, two.id, one.id])
    assert [t.name for t in revoked] == ["one", "two"]
    assert all(t.revoked_at is not None for t in revoked)


def test_a_batch_changes_every_user_or_none_and_names_the_refused(
    services: Services,
) -> None:
    from benethos_mailbox_service.errors import BadRequestError

    from ...conftest import ADMIN

    one = services.users.create_user(ADMIN, "one", [], [])
    narrow = Access("usr_n", "narrow", [], service=["users.manage"])
    wide = services.users.create_user(ADMIN, "wide", [], [], service=["admin"])
    done = services.users.change_users(narrow, [one.id, wide.id], "disable")
    assert done.changed == []
    [(name, why)] = done.refused
    assert name == "wide" and "lacks" in why
    assert not services.users.get_user(ADMIN, one.id).disabled
    alone = services.users.change_users(narrow, [one.id], "disable")
    assert [u.name for u in alone.changed] == ["one"]
    with pytest.raises(BadRequestError):
        services.users.change_users(ADMIN, [one.id], "promote")
    with pytest.raises(BadRequestError):
        services.users.change_users(ADMIN, [one.id], "give_role")
    unknown = services.users.change_users(ADMIN, [one.id], "give_role", "nobody")
    assert unknown.refused == [("one", "unknown role: nobody")]


def test_a_batch_counts_only_the_users_it_changed(services: Services) -> None:
    from ...conftest import ADMIN

    one = services.users.create_user(ADMIN, "one", [], [])
    two = services.users.create_user(ADMIN, "two", [], [])
    services.users.update_user(ADMIN, two.id, disabled=True)
    services.roles.create_role(ADMIN, "helper", [])
    disabled = services.users.change_users(ADMIN, [one.id, two.id], "disable")
    assert [u.name for u in disabled.changed] == ["one"]
    taken = services.users.change_users(ADMIN, [one.id, two.id], "take_role", "helper")
    assert taken.changed == [] and taken.refused == []


def test_a_batch_leaves_an_administrator_counting_every_user() -> None:
    """Each of two administrators could be disabled alone, not both."""
    from benethos_mailbox_service.assembly import build_services
    from benethos_mailbox_service.config import Settings
    from benethos_mailbox_service.errors import ConflictError

    from ...conftest import ADMIN

    services = build_services(Settings(storage="memory"))
    first = services.users.create_user(
        ADMIN, "first", [], [], service=["admin"], ui_sign_in=True
    )
    second = services.users.create_user(
        ADMIN, "second", [], [], service=["admin"], ui_sign_in=True
    )
    with pytest.raises(ConflictError, match="no enabled administrator"):
        services.users.change_users(ADMIN, [first.id, second.id], "disable")
    assert not services.users.get_user(ADMIN, first.id).disabled
    assert not services.users.get_user(ADMIN, second.id).disabled
