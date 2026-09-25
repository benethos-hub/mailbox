"""The user, token and role pages of the configuration UI."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import FormData

from benethos_mailbox_api.data.models import Grant
from benethos_mailbox_api.errors import MailboxApiError
from benethos_mailbox_api.main import Services
from benethos_mailbox_api.web.pages.grants import GrantFormError, read_grants, rows_of

from .conftest import ADMIN, bearer_for
from .ui_helpers import post, sign_in


def _form(**fields: str | list[str]) -> FormData:
    items: list[tuple[str, str]] = []
    for key, value in fields.items():
        for one in value if isinstance(value, list) else [value]:
            items.append((key, one))
    return FormData(items)


# --- the grant editor -----------------------------------------------------------------


def test_the_editor_reads_its_rows_back() -> None:
    grants = read_grants(
        _form(
            grants="3",
            g0_accounts=["acc_a", "acc_b"],
            g0_allow=["mail.read", "send"],
            g0_more="list_accounts, get_account",
            g0_recipients="bot@example.org\n*@example.net",
            g0_max="5",
            g1_accounts="*",
            g1_allow="audit",
            g1_remove="1",
            # the empty row for adding
            g2_recipients="",
        )
    )
    assert grants == [
        Grant(
            accounts=["acc_a", "acc_b"],
            allow=["mail.read", "send", "list_accounts", "get_account"],
            recipients=["bot@example.org", "*@example.net"],
            max_sends_per_day=5,
        )
    ]


def test_rows_round_trip() -> None:
    grant = Grant(
        accounts=["*"],
        allow=["mail.read", "list_accounts"],
        recipients=["*@example.org"],
        max_sends_per_day=3,
    )
    rows = rows_of([grant])
    assert len(rows) == 2 and rows[1].accounts == []
    assert rows[0].groups == ["mail.read"] and rows[0].more == "list_accounts"
    fields: dict[str, str | list[str]] = {"grants": "1"}
    fields.update(
        g0_accounts=rows[0].accounts,
        g0_allow=rows[0].groups,
        g0_more=rows[0].more,
        g0_recipients=rows[0].recipients,
        g0_max=str(rows[0].max_sends_per_day),
    )
    assert read_grants(_form(**fields)) == [grant]


def test_a_bad_recipient_is_named() -> None:
    with pytest.raises(GrantFormError, match=r"grant 1: nobody is not an address"):
        read_grants(
            _form(grants="1", g0_accounts="*", g0_allow="send", g0_recipients="nobody")
        )


def test_sends_per_day_must_be_a_number() -> None:
    with pytest.raises(GrantFormError, match="must be a number"):
        read_grants(_form(grants="1", g0_accounts="*", g0_allow="send", g0_max="x"))


# --- users ----------------------------------------------------------------------------


def test_create_a_user_with_a_constrained_grant(
    ui: TestClient, services: Services, account_id: str
) -> None:
    form = ui.get("/ui/users/new").text
    assert "me@example.com" in form and "every account, also later ones" in form
    created = post(
        ui,
        "/ui/users",
        {
            "name": "desktop",
            "grants": "1",
            "g0_accounts": account_id,
            "g0_allow": ["mail.read", "send"],
            "g0_recipients": "bot@example.org",
            "g0_max": "2",
        },
    )
    assert "desktop created." in created.text
    [user] = [u for u in services.users.list_users(ADMIN) if u.name == "desktop"]
    assert user.grants == [
        Grant(
            accounts=[account_id],
            allow=["mail.read", "send"],
            recipients=["bot@example.org"],
            max_sends_per_day=2,
        )
    ]
    listed = ui.get("/ui/users").text
    assert "desktop" in listed and "sending to" in listed and "mails a day" in listed


def test_a_user_without_a_name_is_refused(ui: TestClient) -> None:
    answer = post(ui, "/ui/users", {"name": " "}, follow_redirects=False)
    # The domain refuses it, and the page shows its words.
    assert "err=a+user+needs+a+name" in answer.headers["location"]


def test_change_disable_and_delete_a_user(ui: TestClient, services: Services) -> None:
    user = services.users.create_user(
        ADMIN, "helper", [], [Grant(accounts=["*"], allow=["mail.read"])]
    )
    url = f"/ui/users/{user.id}"
    page = ui.get(url).text
    assert 'value="helper"' in page and "Delete user" in page
    saved = post(
        ui,
        url,
        {
            "name": "helper2",
            "disabled": "1",
            "grants": "2",
            "g0_accounts": "*",
            "g0_allow": "mail.read",
            "g0_remove": "1",
            "g1_accounts": "*",
            "g1_allow": "audit",
        },
    )
    assert "Saved." in saved.text
    changed = services.users.get_user(ADMIN, user.id)
    assert changed.name == "helper2" and changed.disabled
    assert changed.grants == [Grant(accounts=["*"], allow=["audit"])]
    deleted = post(ui, f"{url}/delete")
    assert "User deleted" in deleted.text
    assert ui.get(url).status_code == 404


def test_no_escalation_through_the_form(
    app_client: TestClient, services: Services, account_id: str
) -> None:
    headers = bearer_for(
        services,
        Grant(accounts=[account_id], allow=["users.manage", "mail.read"]),
    )
    sign_in(app_client, headers["Authorization"].removeprefix("Bearer "))
    refused = post(
        app_client,
        "/ui/users",
        {"name": "wider", "grants": "1", "g0_accounts": "*", "g0_allow": "admin"},
    )
    assert "cannot grant or manage rights the caller lacks" in refused.text
    assert "wider" not in [u.name for u in services.users.list_users(ADMIN)]


# --- tokens ---------------------------------------------------------------------------


def test_a_new_token_is_shown_once_and_never_in_the_url(
    ui: TestClient, services: Services
) -> None:
    user = services.users.create_user(ADMIN, "bot", [], [])
    url = f"/ui/users/{user.id}"
    answer = post(
        ui, f"{url}/tokens", {"name": "laptop", "days": "30"}, follow_redirects=False
    )
    assert answer.headers["location"] == url
    page = ui.get(url).text
    shown = re.search(r'<code class="secret">([^<]+)</code>', page)
    assert shown is not None
    plain = shown.group(1)
    assert services.auth.authenticate(plain).user_id == user.id
    [token] = services.users.list_tokens(ADMIN, user.id)
    assert token.name == "laptop" and token.expires_at is not None
    again = ui.get(url).text
    assert plain not in again and "shown this once" not in again
    assert "laptop" in again


def test_revoke_a_token(ui: TestClient, services: Services) -> None:
    user = services.users.create_user(ADMIN, "bot", [], [])
    token, plain = services.auth.issue_token(user.id, "old")
    url = f"/ui/users/{user.id}"
    assert "Revoke" in ui.get(url).text
    revoked = post(ui, f"{url}/tokens/{token.id}/revoke")
    assert "Token old revoked." in revoked.text
    assert "revoked" in revoked.text
    with pytest.raises(MailboxApiError):
        services.auth.authenticate(plain)


def test_token_days_must_be_a_number(ui: TestClient, services: Services) -> None:
    user = services.users.create_user(ADMIN, "bot", [], [])
    answer = post(
        ui,
        f"/ui/users/{user.id}/tokens",
        {"name": "t", "days": "soon"},
        follow_redirects=False,
    )
    assert "err=Days+valid" in answer.headers["location"]
    assert services.users.list_tokens(ADMIN, user.id) == []


# --- roles ----------------------------------------------------------------------------


def test_create_change_and_delete_a_role(ui: TestClient, services: Services) -> None:
    created = post(
        ui,
        "/ui/roles",
        {"id": "reader", "grants": "1", "g0_accounts": "*", "g0_allow": "mail.read"},
    )
    assert "Role reader created." in created.text
    assert services.users.get_role(ADMIN, "reader").grants == [
        Grant(accounts=["*"], allow=["mail.read"])
    ]
    post(
        ui,
        "/ui/roles/reader",
        {"grants": "1", "g0_accounts": "*", "g0_allow": ["mail.read", "audit"]},
    )
    assert services.users.get_role(ADMIN, "reader").grants[0].allow == [
        "mail.read",
        "audit",
    ]
    holder = services.users.create_user(ADMIN, "holder", ["reader"], [])
    page = ui.get("/ui/roles/reader").text
    assert "holder" in page
    refused = post(ui, "/ui/roles/reader/delete")
    assert "is used by" in refused.text
    services.users.delete_user(ADMIN, holder.id)
    deleted = post(ui, "/ui/roles/reader/delete")
    assert "Role reader deleted." in deleted.text


def test_a_user_keeps_roles_the_editor_cannot_list(
    app_client: TestClient, services: Services
) -> None:
    services.users.create_role(ADMIN, "hidden", [])
    target = services.users.create_user(ADMIN, "target", ["hidden"], [])
    headers = bearer_for(
        services,
        Grant(accounts=["*"], allow=["list_users", "get_user", "update_user"]),
    )
    sign_in(app_client, headers["Authorization"].removeprefix("Bearer "))
    page = app_client.get(f"/ui/users/{target.id}").text
    assert 'name="roles" value="hidden" checked' in page
    post(
        app_client,
        f"/ui/users/{target.id}",
        {"name": "target", "roles": "hidden", "grants": "0"},
    )
    assert services.users.get_user(ADMIN, target.id).roles == ["hidden"]


def test_a_role_name_is_quoted_in_links(ui: TestClient, services: Services) -> None:
    services.users.create_role(ADMIN, "team a&b", [])
    listed = ui.get("/ui/roles").text
    assert 'href="/ui/roles/team%20a%26b"' in listed
    assert "Role team a&amp;b" in ui.get("/ui/roles/team%20a%26b").text


def test_the_sidebar_links_the_access_pages(ui: TestClient) -> None:
    home = ui.get("/ui").text
    assert 'href="/ui/users"' in home and 'href="/ui/roles"' in home
