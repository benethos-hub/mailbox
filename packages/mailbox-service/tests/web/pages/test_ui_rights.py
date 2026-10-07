"""The user pages of the configuration UI: effective rights, a refused
editor that keeps what was typed, expiry and folders in the editor."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.data.models import Grant
from benethos_mailbox_service.domain.rights import permissions
from benethos_mailbox_service.domain.rights.access import Access
from benethos_mailbox_service.web.pages.grants import (
    GROUP_NAMES,
    GROUP_SECTIONS,
    MCP_TOOLS,
    group_hint,
)

from ...conftest import ADMIN, browser_user
from ...ui_helpers import post, sign_in

# --- effective rights ------------------------------------------------------------


def test_summarize_names_whole_groups_and_the_rest() -> None:
    groups, rest = permissions.summarize(
        [*permissions.GROUPS["mail.read"], "create_draft"], permissions.ON_AN_ACCOUNT
    )
    assert groups == ["mail.read"]
    assert rest == ["create_draft"]


def test_rights_of_joins_roles_and_grants(services: Services, account_id: str) -> None:
    services.roles.create_role(
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
    services.roles.create_role(
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


# --- a refused editor keeps what was typed (docs/UI.md 4.7) ------------------------


def test_a_refused_new_user_keeps_what_was_typed(
    ui: TestClient, services: Services, account_id: str
) -> None:
    services.roles.create_role(ADMIN, "readers", [])
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
    assert services.tokens.list_tokens(ADMIN, user.id) == []


def test_a_refused_role_keeps_its_rows(ui: TestClient, services: Services) -> None:
    fields = {"grants": "1", "g0_accounts": "*", "g0_allow": "mail.read"}
    refused = post(ui, "/ui/roles", {"id": "helpers", **fields, "g0_max": "x"})
    assert refused.status_code == 400
    assert 'name="id" value="helpers"' in refused.text
    assert 'name="g0_max" inputmode="numeric" value="x"' in refused.text
    services.roles.create_role(ADMIN, "readers", [])
    changed = post(ui, "/ui/roles/readers", {**fields, "g0_more": "no_such_right"})
    assert changed.status_code == 400
    assert 'value="no_such_right"' in changed.text
    assert services.roles.get_role(ADMIN, "readers").grants == []


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


def test_the_editor_narrows_a_grant_to_folders(
    ui: TestClient, services: Services
) -> None:
    made = post(
        ui,
        "/ui/users",
        {
            "name": "bookkeeper",
            "grants": "1",
            "g0_accounts": "*",
            "g0_allow": "mail.read",
            "g0_folders": "inbox\r\nInvoices 2026\r\n",
        },
    )
    assert "bookkeeper created" in made.text
    user = services.auth.user_named("bookkeeper")
    assert user is not None
    assert user.grants[0].folders == ["inbox", "Invoices 2026"]
    page = ui.get(f"/ui/users/{user.id}").text
    assert "in the folders</span> inbox, Invoices 2026" in page
    assert ">inbox\nInvoices 2026</textarea>" in page
