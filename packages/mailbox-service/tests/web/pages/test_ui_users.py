"""The user, token and role pages of the configuration UI."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import FormData

from benethos_mailbox_service.data.models import Grant
from benethos_mailbox_service.domain.rights import permissions
from benethos_mailbox_service.domain.rights.access import Access
from benethos_mailbox_service.errors import MailboxServiceError
from benethos_mailbox_service.main import Services
from benethos_mailbox_service.web.pages.grants import (
    GROUP_NAMES,
    GROUP_SECTIONS,
    MCP_TOOLS,
    ROLE_TEMPLATES,
    GrantFormError,
    group_hint,
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
    page = ui.get(f"/ui/users/{bot.id}").text
    assert "off: an API user, tokens only" in page and "API only" in page
    assert "Set password" not in page
    saved = post(
        ui,
        f"/ui/users/{bot.id}",
        {"name": "bot", "ui_sign_in_shown": "1", "ui_sign_in": "1"},
    )
    assert "not possible: no password yet" in saved.text
    assert "Set password" in saved.text and "Make a one-time password" in saved.text
    secret = "a password for the bot user"
    post(
        ui,
        f"/ui/users/{bot.id}/password",
        {"new_password": secret, "repeat_password": secret},
    )
    assert "with a password" in ui.get(f"/ui/users/{bot.id}").text
    own = services.auth.user_named("admin")
    assert own is not None
    mine = ui.get(f"/ui/users/{own.id}").text
    assert "Change your password" in mine and "Set password" not in mine
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
    assert services.users.list_tokens(ADMIN, user.id) == []
    answer = post(
        ui,
        f"/ui/users/{user.id}/tokens",
        {"name": "t", "days": "99999999999"},
    )
    assert "from 1 to 3650" in answer.text
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
    sign_in(
        app_client,
        *browser_user(
            services,
            service=["list_users", "get_user", "update_user"],
        ),
    )
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


# --- effective rights ------------------------------------------------------------


def test_summarize_names_whole_groups_and_the_rest() -> None:
    groups, rest = permissions.summarize(
        [*permissions.GROUPS["mail.read"], "create_draft"], permissions.ON_AN_ACCOUNT
    )
    assert groups == ["mail.read"]
    assert rest == ["create_draft"]


def test_rights_of_joins_roles_and_grants(services: Services, account_id: str) -> None:
    services.users.create_role(
        ADMIN, "reader", [Grant(accounts=["*"], allow=["mail.read"])]
    )
    user = services.users.create_user(
        ADMIN,
        "desktop",
        ["reader"],
        [
            Grant(
                accounts=[account_id],
                allow=["drafts", "send"],
                recipients=["bot@example.org"],
                max_sends_per_day=3,
            )
        ],
    )
    rights = services.users.rights_of(ADMIN, user.id)
    [account] = rights.accounts
    assert {"get_message", "create_draft", "send_message"} <= set(account.operations)
    assert [(s.recipients, s.max_sends_per_day) for s in account.sending] == [
        (["bot@example.org"], 3)
    ]
    assert account.warnings == []


def test_rights_of_lists_only_accounts_the_caller_sees(
    services: Services, account_id: str
) -> None:
    user = services.users.create_user(
        ADMIN, "reader", [], [Grant(accounts=["*"], allow=["mail.read"])]
    )
    manager = Access("usr_m", "manager", [], service=["users.manage"])
    assert services.users.rights_of(manager, user.id).accounts == []
    assert len(services.users.rights_of(ADMIN, user.id).accounts) == 1


def test_the_user_page_shows_the_effective_rights(
    ui: TestClient, services: Services, account_id: str
) -> None:
    services.users.create_role(
        ADMIN, "reader", [Grant(accounts=["*"], allow=["mail.read"])]
    )
    user = services.users.create_user(
        ADMIN,
        "desktop",
        ["reader"],
        [Grant(accounts=[account_id], allow=["send", "list_accounts"])],
    )
    page = ui.get(f"/ui/users/{user.id}").text
    section = page.split("Effective rights", 1)[1]
    assert "me@example.com" in section
    assert ">mail.read<" in section and ">send<" in section
    assert ">list_accounts<" in section
    assert "reads and sends anywhere" in section
    assert "to anyone, no daily limit" in section


MCP_README = Path(__file__).resolve().parents[5] / "packages/mailbox-mcp/README.md"


def test_the_mcp_tools_shown_are_those_of_the_mcp_readme() -> None:
    """grants.MCP_TOOLS repeats the tool table of the MCP server's README,
    the one place that documents which right opens which tool."""
    rows = re.findall(
        r"^\| `(\w+)` \| `([\w.]+)` \|", MCP_README.read_text(encoding="utf-8"), re.M
    )
    documented: dict[str, list[str]] = {}
    for tool, group in rows:
        documented.setdefault(group, []).append(tool)
    assert {group: tuple(tools) for group, tools in documented.items()} == MCP_TOOLS


def test_the_editor_sorts_every_group_into_one_row() -> None:
    names = [name for _, section in GROUP_SECTIONS for name in section]
    assert sorted(names) == sorted(GROUP_NAMES)
    assert set(MCP_TOOLS) <= set(permissions.GROUPS)
    assert "MCP tools: list_folders, search_messages" in group_hint("mail.read")
    assert "MCP tools" not in group_hint("mail.delete")
    assert "does not need it" in group_hint("accounts.read")


def test_the_editor_shows_what_the_mcp_server_uses(ui: TestClient) -> None:
    form = ui.get("/ui/users/new").text
    used, rest = form.split("Not used by the MCP server", 1)
    assert "Used by the MCP server" in used
    assert 'value="send"' in used.split("Used by the MCP server", 1)[1]
    assert 'value="mail.delete"' in rest and 'value="admin"' not in rest
    service = used.split("Used by the MCP server", 1)[0]
    assert 'name="service" value="admin"' in service
    assert 'name="service" value="accounts.connect"' in service


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
    shown = re.search(r'<code class="secret">([^<]+)</code>', created.text)
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


def test_a_new_role_has_its_editor(
    ui: TestClient, app_client: TestClient, services: Services, account_id: str
) -> None:
    page = ui.get("/ui/roles/new")
    assert page.status_code == 200 and "Cancel" in page.text
    assert 'href="/ui/roles/new"' in ui.get("/ui/roles").text
    created = post(ui, "/ui/roles", {"id": "helpers", "grants": "0"})
    assert "Role helpers created." in created.text
    refused = post(ui, "/ui/roles", {"id": "", "grants": "0"})
    assert refused.status_code == 400 and "Cancel" in refused.text

    reader = TestClient(app_client.app)
    sign_in(
        reader,
        *browser_user(services, Grant(accounts=[account_id], allow=["mail.read"])),
    )
    assert reader.get("/ui/roles/new").status_code == 403


def test_users_filter_by_name_role_and_state(
    ui: TestClient, services: Services
) -> None:
    services.users.create_role(ADMIN, "readers", [])
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
    assert '<code class="secret">' not in created.text
    assert "off: an API user, tokens only" in created.text
    listed = ui.get("/ui/users", params={"api_only": "1"}).text
    assert ">script</a>" in listed and ">admin</a>" not in listed
    assert "API only" in listed
    user = services.auth.user_named("script")
    assert user is not None and user.ui_sign_in is False


# --- a refused editor keeps what was typed (docs/UI.md 4.7) ------------------------


def test_a_refused_new_user_keeps_what_was_typed(
    ui: TestClient, services: Services, account_id: str
) -> None:
    services.users.create_role(ADMIN, "readers", [])
    services.users.create_user(ADMIN, "taken", [], [])
    refused = post(
        ui,
        "/ui/users",
        {
            "name": "Taken",
            "signs_in_to": "ui",
            "roles": "readers",
            "grants": "1",
            "g0_accounts": account_id,
            "g0_allow": "mail.read",
            "g0_recipients": "*@example.org",
            "g0_max": "7",
        },
    )
    assert refused.status_code == 400
    page = refused.text
    assert 'role="alert"' in page and "taken" in page.lower()
    assert 'name="name" value="Taken"' in page
    assert 'value="ui" checked' in page
    assert 'value="readers" checked' in page
    assert f'name="g0_accounts" value="{account_id}" checked' in page
    assert 'name="g0_allow" value="mail.read" checked' in page
    assert "*@example.org</textarea>" in page and 'value="7"' in page


def test_a_refused_change_keeps_what_was_typed(
    ui: TestClient, services: Services
) -> None:
    user = services.users.create_user(ADMIN, "someone", [], [])
    refused = post(
        ui,
        f"/ui/users/{user.id}",
        {
            "name": "Renamed",
            "ui_sign_in_shown": "1",
            "disabled": "1",
            "grants": "1",
            "g0_accounts": "*",
            "g0_allow": "mail.read",
            "g0_max": "many",
        },
    )
    assert refused.status_code == 400
    page = refused.text
    assert "sends per day must be a number" in page
    assert 'name="name" value="Renamed"' in page
    assert 'name="disabled" value="1" checked' in page
    assert '<details class="fold" open>' in page and 'value="many"' in page
    assert services.users.get_user(ADMIN, user.id).name == "someone"


@pytest.mark.parametrize("days", ["soon", "0", "3651"])
def test_a_refused_token_keeps_its_name(
    ui: TestClient, services: Services, days: str
) -> None:
    user = services.users.create_user(ADMIN, "bot", [], [])
    refused = post(ui, f"/ui/users/{user.id}/tokens", {"name": "laptop", "days": days})
    assert refused.status_code == 400
    assert "Days valid must be a whole number from 1 to 3650" in refused.text
    assert 'name="name" value="laptop"' in refused.text
    assert f'name="days" value="{days}"' in refused.text
    assert services.users.list_tokens(ADMIN, user.id) == []


def test_a_refused_role_keeps_its_rows(ui: TestClient, services: Services) -> None:
    fields = {"grants": "1", "g0_accounts": "*", "g0_allow": "mail.read"}
    refused = post(ui, "/ui/roles", {"id": "helpers", **fields, "g0_max": "x"})
    assert refused.status_code == 400
    assert 'name="id" value="helpers"' in refused.text
    assert 'name="g0_max" inputmode="numeric" value="x"' in refused.text
    services.users.create_role(ADMIN, "readers", [])
    changed = post(ui, "/ui/roles/readers", {**fields, "g0_more": "no_such_right"})
    assert changed.status_code == 400
    assert 'value="no_such_right"' in changed.text
    assert services.users.get_role(ADMIN, "readers").grants == []


def test_a_page_looks_its_session_up_once(
    ui: TestClient, services: Services, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = services.users.create_user(ADMIN, "bot", [], [])
    looked_up = []
    lookup = services.auth.session_access

    def counted(*args: object, **kwargs: object) -> Access:
        looked_up.append(args)
        return lookup(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(services.auth, "session_access", counted)
    ui.get(f"/ui/users/{user.id}")
    assert len(looked_up) == 1


def test_users_read_opens_the_pages_and_changes_nothing(
    app_client: TestClient, services: Services
) -> None:
    target = services.users.create_user(ADMIN, "target", [], [])
    sign_in(app_client, *browser_user(services, service=["users.read"]))
    home = app_client.get("/ui").text
    assert 'href="/ui/users"' in home and 'href="/ui/roles"' in home
    page = app_client.get(f"/ui/users/{target.id}").text
    assert "Effective rights" in page and "Tokens" in page
    assert 'name="service"' not in page and "New user" not in page
    refused = post(app_client, f"/ui/users/{target.id}", {"name": "x", "grants": "0"})
    assert "missing right: update_user" in refused.text


def test_the_editor_sets_and_shows_an_expiry(
    ui: TestClient, services: Services
) -> None:
    made = post(
        ui,
        "/ui/users",
        {
            "name": "week",
            "grants": "2",
            "g0_accounts": "*",
            "g0_allow": "mail.read",
            "g0_expires": "2099-12-31T18:30",
            "g1_accounts": "*",
            "g1_allow": "drafts",
            "g1_expires": "2001-01-01T00:00",
        },
    )
    assert "week created" in made.text
    user = services.auth.user_named("week")
    assert user is not None
    first, second = (grant.expires_at for grant in user.grants)
    assert first is not None and second is not None
    assert first.astimezone().strftime("%Y-%m-%dT%H:%M") == "2099-12-31T18:30"
    page = ui.get(f"/ui/users/{user.id}").text
    assert 'name="g0_expires" type="datetime-local" value="2099-12-31T18:30"' in page
    assert "until</span> 2099-12-31 18:30" in page
    assert '<span class="tag bad">expired</span>' in page


def test_a_wrong_expiry_is_refused(ui: TestClient) -> None:
    refused = post(
        ui,
        "/ui/users",
        {
            "name": "x",
            "grants": "1",
            "g0_accounts": "*",
            "g0_allow": "mail.read",
            "g0_expires": "next week",
        },
    )
    assert refused.status_code == 400
    assert "valid until must be a date and a time" in refused.text


def test_the_overview_names_the_own_sending_limits(
    app_client: TestClient, services: Services, account_id: str
) -> None:
    sign_in(
        app_client,
        *browser_user(
            services,
            Grant(
                accounts=[account_id],
                allow=["mail.read", "send"],
                recipients=["*@example.org"],
                max_sends_per_day=2,
            ),
        ),
    )
    home = app_client.get("/ui").text
    assert "to *@example.org, at most 2 a day, 2 left now" in home


# --- roles to start from (PERMISSIONS.md 8.7) ------------------------------------


def test_the_new_role_page_offers_four_templates(ui: TestClient) -> None:
    page = ui.get("/ui/roles/new").text
    for template in ("reader", "agent", "sender", "operator"):
        assert f'href="/ui/roles/new?template={template}"' in page
    assert [t.title for t in ROLE_TEMPLATES.values()] == [
        "Reader",
        "Agent",
        "Sender",
        "Operator",
    ]


@pytest.mark.parametrize("template", list(ROLE_TEMPLATES))
def test_every_template_names_rights_of_the_right_kind(template: str) -> None:
    chosen = ROLE_TEMPLATES[template]
    permissions.check_service(chosen.service)
    for grant in chosen.grants:
        permissions.check_grant(grant.allow)


def test_a_template_fills_the_form(ui: TestClient, account_id: str) -> None:
    agent = ui.get("/ui/roles/new?template=agent").text
    assert 'name="id" value="agent"' in agent
    for group in ("mail.read", "mail.write", "drafts"):
        assert f'name="g0_allow" value="{group}" checked' in agent
    assert 'name="g0_allow" value="send" checked' not in agent
    assert f'name="g0_accounts" value="{account_id}" checked' not in agent
    operator = ui.get("/ui/roles/new?template=operator").text
    assert 'name="service" value="accounts.connect" checked' in operator
    assert 'name="service" value="webhooks.manage" checked' in operator
    assert 'name="g0_accounts" value="*" checked' in operator
    assert 'name="g0_allow" value="accounts.manage" checked' in operator
    unknown = ui.get("/ui/roles/new?template=nothing").text
    assert 'name="id" value=""' in unknown


def test_the_sender_template_wants_recipients(
    ui: TestClient, services: Services, account_id: str
) -> None:
    form = {
        "template": "sender",
        "id": "sender",
        "grants": "1",
        "g0_accounts": account_id,
        "g0_allow": "send",
        "g0_max": "10",
    }
    refused = post(ui, "/ui/roles", form)
    assert refused.status_code == 400
    assert "name the recipients it may send to" in refused.text
    assert 'name="template" value="sender"' in refused.text
    made = post(ui, "/ui/roles", {**form, "g0_recipients": "*@example.org"})
    assert "Role sender created." in made.text
    [grant] = services.users.get_role(ADMIN, "sender").grants
    assert grant.recipients == ["*@example.org"] and grant.max_sends_per_day == 10
