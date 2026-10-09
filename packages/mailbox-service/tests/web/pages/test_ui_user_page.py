"""A user's page in tabs, the grant editor in lines, and the batch of the
users list (docs/UI.md 6.3)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.data.models import Grant

from ...conftest import ADMIN, browser_user
from ...ui_helpers import post, sign_in

READER = Grant(accounts=["*"], allow=["mail.read"])

# --- tabs -----------------------------------------------------------------------------


def test_the_tabs_split_rights_access_and_activity(
    ui: TestClient, services: Services
) -> None:
    bot = services.users.create_user(ADMIN, "bot", [], [])
    base = f"/ui/users/{bot.id}"
    rights = ui.get(base).text
    assert f'<a href="{base}?tab=rights" class="active" aria-current="page">' in rights
    assert "Effective rights" in rights and "<h2>Change</h2>" in rights
    assert "<h2>Tokens</h2>" not in rights
    access = ui.get(f"{base}?tab=access").text
    assert "<h2>Sign-in</h2>" in access and "<h2>Tokens</h2>" in access
    assert "Effective rights" not in access
    activity = ui.get(f"{base}?tab=activity").text
    assert "Recent activity" in activity
    # The Danger card stays below the tabs, on every one of them.
    for page in (rights, access, activity):
        assert "Delete user" in page
    # An unknown tab is Rights.
    assert "Effective rights" in ui.get(f"{base}?tab=nothing").text


def test_no_activity_tab_without_the_audit(
    app_client: TestClient, services: Services
) -> None:
    bot = services.users.create_user(ADMIN, "bot", [], [])
    sign_in(app_client, *browser_user(services, service=["users.read"]))
    page = app_client.get(f"/ui/users/{bot.id}?tab=activity").text
    assert "?tab=activity" not in page and "Effective rights" in page


def test_a_refused_change_comes_back_on_rights(
    ui: TestClient, services: Services
) -> None:
    bot = services.users.create_user(ADMIN, "bot", [], [])
    refused = post(ui, f"/ui/users/{bot.id}?tab=access", {"name": "admin"})
    assert refused.status_code == 400 and "<h2>Change</h2>" in refused.text


# --- the grant editor -----------------------------------------------------------------


def test_each_grant_is_a_line_with_its_pencil_and_bin(
    ui: TestClient, services: Services, account_id: str
) -> None:
    grant = Grant(accounts=[account_id], allow=["mail.read"], max_sends_per_day=5)
    bot = services.users.create_user(ADMIN, "bot", [], [grant])
    page = ui.get(f"/ui/users/{bot.id}").text
    line = page[page.index('<div class="grant-line">') :]
    line = line[: line.index('<div class="row-form')]
    assert "me@example.com" in line and "mail.read" in line and "5" in line
    assert 'aria-label="Change grant 1"' in line
    assert 'name="g0_remove" value="1" aria-label="Remove grant 1"' in line
    # Its fields are folded under it, the new one folded at the top.
    assert '<div class="row-form" id="grant-0">' in page
    assert '<div class="row-form" id="grant-new">' in page
    removed = post(
        ui,
        f"/ui/users/{bot.id}",
        {
            "name": "bot",
            "grants": "2",
            "g0_accounts": account_id,
            "g0_allow": "mail.read",
            "g0_remove": "1",
        },
    )
    assert "Saved." in removed.text
    assert services.users.get_user(ADMIN, bot.id).grants == []


def test_without_a_grant_the_new_one_is_open(
    ui: TestClient, services: Services
) -> None:
    bot = services.users.create_user(ADMIN, "bot", [], [])
    page = ui.get(f"/ui/users/{bot.id}").text
    assert '<div class="row-form open" id="grant-new">' in page
    assert '<div class="grant-line">' not in page


# --- the batch of the users list ------------------------------------------------------


def test_ticked_users_are_disabled_and_enabled(
    ui: TestClient, services: Services
) -> None:
    one = services.users.create_user(ADMIN, "one", [], [])
    two = services.users.create_user(ADMIN, "two", [], [])
    page = ui.get("/ui/users").text
    assert 'id="users-batch"' in page and f'value="{one.id}" form="users-batch"' in page
    done = post(ui, "/ui/users/batch", {"user": [one.id, two.id], "action": "disable"})
    assert "2 users changed." in done.text
    assert all(services.users.get_user(ADMIN, u.id).disabled for u in (one, two))
    post(ui, "/ui/users/batch", {"user": [one.id], "action": "enable"})
    assert not services.users.get_user(ADMIN, one.id).disabled


def test_a_role_is_given_and_taken_and_the_caller_never_disabled(
    ui: TestClient, services: Services
) -> None:
    services.roles.create_role(ADMIN, "readers", [READER])
    one = services.users.create_user(ADMIN, "one", [], [])
    me = services.auth.user_named("admin")
    assert me is not None
    page = ui.get("/ui/users").text
    assert 'data-show-for="f-users-action:give_role take_role"' in page
    given = post(
        ui,
        "/ui/users/batch",
        {"user": [one.id], "action": "give_role", "role": "readers"},
    )
    assert "1 user changed." in given.text
    assert services.users.get_user(ADMIN, one.id).roles == ["readers"]
    post(
        ui,
        "/ui/users/batch",
        {"user": [one.id], "action": "take_role", "role": "readers"},
    )
    assert services.users.get_user(ADMIN, one.id).roles == []
    mixed = post(ui, "/ui/users/batch", {"user": [one.id, me.id], "action": "disable"})
    assert "Nothing changed. admin: a user cannot disable itself." in mixed.text
    assert not services.users.get_user(ADMIN, me.id).disabled
    # All or nothing: the one the caller may disable stays enabled too.
    assert not services.users.get_user(ADMIN, one.id).disabled


def test_a_batch_needs_ticks_and_a_role_where_it_gives_one(ui: TestClient) -> None:
    nothing = post(ui, "/ui/users/batch", {"action": "disable"})
    assert "tick at least one user" in nothing.text
    roleless = post(ui, "/ui/users/batch", {"user": ["usr_x"], "action": "give_role"})
    assert "choose a role" in roleless.text


def test_a_reader_has_no_batch(app_client: TestClient, services: Services) -> None:
    services.users.create_user(ADMIN, "one", [], [])
    sign_in(app_client, *browser_user(services, service=["users.read"]))
    page = app_client.get("/ui/users").text
    assert 'id="users-batch"' not in page and 'form="users-batch"' not in page
