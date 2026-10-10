"""The user and token pages of the configuration UI, and its grant editor."""

from __future__ import annotations

import html
import re

import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import FormData

from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.data.models import Grant
from benethos_mailbox_service.errors import MailboxServiceError
from benethos_mailbox_service.web.pages.grants import (
    GrantFormError,
    read_grants,
    rows_of,
)

from ...conftest import ADMIN, browser_user
from ...ui_helpers import post, sign_in


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
        g0_max=rows[0].max_per_day,
    )
    assert read_grants(_form(**fields)) == [grant]


def test_a_bad_recipient_is_named() -> None:
    with pytest.raises(GrantFormError, match=r"grant 1: nobody is not an address"):
        read_grants(
            _form(grants="1", g0_accounts="*", g0_allow="send", g0_recipients="nobody")
        )


def test_the_row_count_is_capped_before_the_rows_are_read() -> None:
    with pytest.raises(GrantFormError, match="100 grants at most"):
        read_grants(_form(grants="2000000000"))
    assert read_grants(_form(grants="100")) == []


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
    answer = post(ui, "/ui/users", {"name": " "})
    # The domain refuses it, and the page shows its words.
    assert "a user needs a name" in answer.text


def test_the_page_says_whether_a_user_can_sign_in(
    ui: TestClient, services: Services
) -> None:
    bot = services.users.create_user(ADMIN, "bot", [], [])
    access = f"/ui/users/{bot.id}?tab=access"
    page = ui.get(access).text
    assert "off: an API user, tokens only" in page and "API only" in page
    assert "Set password" not in page
    post(
        ui,
        f"/ui/users/{bot.id}",
        {"name": "bot", "ui_sign_in_shown": "1", "ui_sign_in": "1"},
    )
    saved = ui.get(access).text
    assert "not possible: no password yet" in saved
    assert "Set password" in saved and "Make a one-time password" in saved
    secret = "a password for the bot user"
    post(
        ui,
        f"/ui/users/{bot.id}/password",
        {"new_password": secret, "repeat_password": secret},
    )
    set_for_it = ui.get(access).text
    assert "with a password set for it, to change at the next sign-in" in set_for_it
    own = services.auth.user_named("admin")
    assert own is not None
    mine = ui.get(f"/ui/users/{own.id}?tab=access").text
    # Its own password is changed on its own page, never set for it.
    assert "Set password" not in mine and "Make a one-time password" not in mine
    assert '<a href="/ui/password">Change your password</a>' in mine
    mine = ui.get(f"/ui/users/{own.id}").text
    # Nobody disables itself or takes its own sign-in: no tick boxes there.
    assert 'name="disabled"' not in mine and 'name="ui_sign_in"' not in mine


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
    sign_in(
        app_client,
        *browser_user(
            services,
            Grant(accounts=[account_id], allow=["mail.read"]),
            service=["users.manage"],
        ),
    )
    refused = post(
        app_client, "/ui/users", {"name": "wider", "grants": "0", "service": "admin"}
    )
    assert "cannot grant or manage rights the caller lacks" in refused.text
    assert "wider" not in [u.name for u in services.users.list_users(ADMIN)]


def test_the_editor_gives_rights_of_the_service(
    ui: TestClient, services: Services
) -> None:
    made = post(
        ui,
        "/ui/users",
        {
            "name": "operator",
            "service": ["accounts.connect", "webhooks.manage"],
            "service_more": "list_users",
            "grants": "1",
            "g0_accounts": "*",
            "g0_allow": "accounts.manage",
        },
    )
    assert "operator created" in made.text
    user = services.auth.user_named("operator")
    assert user is not None
    assert user.service == ["accounts.connect", "webhooks.manage", "list_users"]
    page = ui.get(f"/ui/users/{user.id}").text
    assert 'name="service" value="webhooks.manage" checked' in page
    assert 'name="service_more" value="list_users"' in page


def test_a_right_of_the_service_in_a_grant_is_refused(
    ui: TestClient, services: Services
) -> None:
    refused = post(
        ui,
        "/ui/users",
        {"name": "x", "grants": "1", "g0_accounts": "*", "g0_more": "users.manage"},
    )
    assert refused.status_code == 400
    assert "users.manage is a right of the service" in refused.text
    assert services.auth.user_named("x") is None


# --- tokens ---------------------------------------------------------------------------


def test_a_new_token_is_shown_once_and_never_in_the_url(
    ui: TestClient, services: Services
) -> None:
    user = services.users.create_user(ADMIN, "bot", [], [])
    base = f"/ui/users/{user.id}"
    url = f"{base}?tab=access"
    answer = post(
        ui, f"{base}/tokens", {"name": "laptop", "days": "30"}, follow_redirects=False
    )
    assert answer.headers["location"] == url
    page = ui.get(url).text
    shown = re.search(r'<code class="secret"[^>]*>([^<]+)</code>', page)
    assert shown is not None
    plain = shown.group(1)
    assert services.auth.authenticate(plain).user_id == user.id
    [token] = services.tokens.list_tokens(ADMIN, user.id)
    assert token.name == "laptop" and token.expires_at is not None
    again = ui.get(url).text
    assert plain not in again and "shown this once" not in again
    assert "laptop" in again


def test_revoke_a_token(ui: TestClient, services: Services) -> None:
    user = services.users.create_user(ADMIN, "bot", [], [])
    issued = services.auth.issue_token(user.id, "old")
    token, plain = issued.token, issued.plain
    url = f"/ui/users/{user.id}"
    assert "Revoke" in ui.get(f"{url}?tab=access").text
    revoked = post(ui, f"{url}/tokens/{token.id}/revoke")
    assert "Token old revoked." in revoked.text
    assert "revoked" in revoked.text
    with pytest.raises(MailboxServiceError):
        services.auth.authenticate(plain)


def test_token_days_must_be_a_number(ui: TestClient, services: Services) -> None:
    user = services.users.create_user(ADMIN, "bot", [], [])
    answer = post(
        ui,
        f"/ui/users/{user.id}/tokens",
        {"name": "t", "days": "soon"},
    )
    assert "Days valid" in answer.text
    assert services.tokens.list_tokens(ADMIN, user.id) == []
    answer = post(
        ui,
        f"/ui/users/{user.id}/tokens",
        {"name": "t", "days": "99999999999"},
    )
    assert "from 1 to 3650" in answer.text
    assert services.tokens.list_tokens(ADMIN, user.id) == []


def test_a_new_user_gets_a_one_time_password_shown_once(
    ui: TestClient, app_client: TestClient
) -> None:
    form = ui.get("/ui/users/new").text
    assert 'name="one_time" value="1" checked' in form
    assert '<a href="/ui/users">Users</a>' in form  # the breadcrumb
    created = post(
        ui,
        "/ui/users",
        {"name": "Otto", "grants": "0", "signs_in_to": "ui", "one_time": "1"},
    )
    assert "Otto created." in created.text
    shown = re.search(r'<code class="secret"[^>]*>([^<]+)</code>', created.text)
    assert shown is not None
    assert shown.group(1) not in ui.get(str(created.url)).text
    assert "not possible" not in created.text  # it has a password now

    other = TestClient(app_client.app)
    page = other.get("/ui/login")
    nonce = re.search(r'name="nonce" value="([^"]+)"', page.text)
    assert nonce is not None
    landed = other.post(
        "/ui/login",
        data={"name": "otto", "password": shown.group(1), "nonce": nonce.group(1)},
        follow_redirects=False,
    )
    assert landed.headers["location"] == "/ui/password"
    last = ui.get(str(created.url)).text
    assert "Last sign-in</dt><dd>—" not in last


def test_users_filter_by_name_role_and_state(
    ui: TestClient, services: Services
) -> None:
    services.roles.create_role(ADMIN, "readers", [])
    services.users.create_user(ADMIN, "Anna", ["readers"], [])
    bert = services.users.create_user(ADMIN, "Bert", [], [])
    services.users.update_user(ADMIN, bert.id, disabled=True)
    by_name = ui.get("/ui/users", params={"name": "ANN"}).text
    assert ">Anna</a>" in by_name and ">Bert</a>" not in by_name
    by_role = ui.get("/ui/users", params={"role": "readers"}).text
    assert ">Anna</a>" in by_role and ">admin</a>" not in by_role
    assert "Role: readers" in by_role
    disabled = ui.get("/ui/users", params={"disabled": "1"}).text
    assert ">Bert</a>" in disabled and ">Anna</a>" not in disabled
    assert "No user matches." in ui.get("/ui/users", params={"name": "zzz"}).text


def test_a_new_user_is_an_api_user_by_default(
    ui: TestClient, services: Services
) -> None:
    form = ui.get("/ui/users/new").text
    assert 'name="signs_in_to" value="api" checked' in form
    created = post(ui, "/ui/users", {"name": "script", "grants": "0", "one_time": "1"})
    assert "script created." in created.text
    # No one-time password for an API user, though the box was ticked.
    assert '<code class="secret"' not in created.text
    assert '<span class="tag">API only</span>' in created.text
    listed = ui.get("/ui/users", params={"api_only": "1"}).text
    assert ">script</a>" in listed and ">admin</a>" not in listed
    assert "API only" in listed
    user = services.auth.user_named("script")
    assert user is not None and user.ui_sign_in is False


def test_users_page_by_name_with_the_filter(
    ui: TestClient, services: Services, monkeypatch: pytest.MonkeyPatch
) -> None:
    from benethos_mailbox_service.web.pages.routes import users

    monkeypatch.setattr(users, "PAGE_SIZE", 2)
    for name in ("page-c", "Page-a", "page-b"):
        services.users.create_user(ADMIN, name, [], [])
    first = ui.get("/ui/users", params={"name": "page"}).text
    assert ">Page-a</a>" in first and ">page-b</a>" in first
    assert ">page-c</a>" not in first and ">First</a>" not in first
    on = re.search(r'href="([^"]*cursor=[^"]*)">Next', first)
    assert on is not None and "name=page" in on.group(1)
    second = ui.get(html.unescape(on.group(1))).text
    assert ">page-c</a>" in second and ">Page-a</a>" not in second
    assert ">First</a>" in second and ">Next</a>" not in second
