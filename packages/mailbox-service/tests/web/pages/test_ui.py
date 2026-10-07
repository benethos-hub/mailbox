"""The configuration UI: signing in, the session, CSRF, the frame."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service.assembly import Services, create_app
from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.models import Grant
from benethos_mailbox_service.domain.auth.service import SignedIn
from benethos_mailbox_service.web.pages.session import IDLE, SessionStore

from ...conftest import ADMIN, UI_PASSWORD, browser_admin, browser_user
from ...ui_helpers import csrf_of, post, sign_in, try_sign_in

NOW = datetime(2026, 9, 24, 12)
SIGNED = SignedIn(user_id="usr_a", must_change=False, stamp=NOW)

# --- signing in -----------------------------------------------------------------------


def test_a_page_without_a_session_asks_to_sign_in(app_client: TestClient) -> None:
    answer = app_client.get("/ui", follow_redirects=False)
    assert answer.status_code == 303
    assert answer.headers["location"] == "/ui/login?next=/ui"


def test_the_sign_in_leads_back_to_the_page_asked_for(
    app_client: TestClient,
) -> None:
    answer = app_client.get("/ui/mail?folder=inbox&q=x", follow_redirects=False)
    assert (
        answer.headers["location"] == "/ui/login?next=/ui/mail%3Ffolder%3Dinbox%26q%3Dx"
    )
    # A posted form is not repeated: the sign-in lands on the start page.
    answer = app_client.post("/ui/accounts", data={}, follow_redirects=False)
    assert answer.headers["location"] == "/ui/login"


def test_htmx_is_sent_to_the_sign_in_page(app_client: TestClient) -> None:
    answer = app_client.get("/ui", headers={"HX-Request": "true"})
    assert answer.status_code == 204
    assert answer.headers["HX-Redirect"].startswith("/ui/login")


def test_the_form_asks_for_name_and_password(app_client: TestClient) -> None:
    page = app_client.get("/ui/login").text
    assert 'name="name" autocomplete="username"' in page
    assert 'name="password" type="password" autocomplete="current-password"' in page
    assert "token" not in page.lower().replace("csrf", "")


def test_sign_in_sets_a_strict_session_cookie(
    app_client: TestClient, services: Services
) -> None:
    name, password = browser_admin(services)
    answer = try_sign_in(app_client, name, password)
    cookie = answer.headers["set-cookie"]
    assert "mailbox_ui_session=" in cookie
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie and "Path=/ui" in cookie
    assert password not in cookie
    assert app_client.get("/ui").status_code == 200


@pytest.mark.parametrize(
    ("name", "password"),
    [("admin", "a wrong long passphrase"), ("nobody", UI_PASSWORD)],
)
def test_a_wrong_name_or_password_is_refused_alike(
    app_client: TestClient, services: Services, name: str, password: str
) -> None:
    browser_admin(services)
    answer = try_sign_in(app_client, name, password)
    assert answer.headers["location"] == "/ui/login?notice=invalid"
    assert (
        "Wrong user name or password."
        in app_client.get("/ui/login?notice=invalid").text
    )
    assert app_client.get("/ui", follow_redirects=False).status_code == 303


def test_without_any_user_the_page_says_what_to_do(app_client: TestClient) -> None:
    answer = try_sign_in(app_client, "admin", UI_PASSWORD)
    assert answer.headers["location"] == "/ui/login?notice=setup"
    assert "users create-admin" in app_client.get("/ui/login?notice=setup").text


def test_the_sign_in_form_needs_its_nonce(
    app_client: TestClient, services: Services
) -> None:
    """Another site cannot sign this browser in to an account of its own."""
    name, password = browser_admin(services)
    answer = app_client.post(
        "/ui/login",
        data={"name": name, "password": password, "nonce": "forged"},
        follow_redirects=False,
    )
    assert answer.headers["location"] == "/ui/login?notice=expired"
    assert "The sign-in form expired" in app_client.get("/ui/login?notice=expired").text
    assert app_client.get("/ui", follow_redirects=False).status_code == 303


@pytest.mark.parametrize(
    ("query", "shown"),
    [
        ("notice=throttled&minutes=5", "Try again in 5 minutes."),
        ("notice=signed_out", "Signed out."),
        ("notice=anything+you+like", None),
        ("err=Call+this+number", None),
        ("msg=Call+this+number", None),
    ],
)
def test_the_sign_in_page_says_only_its_own_words(
    app_client: TestClient, query: str, shown: str | None
) -> None:
    page = app_client.get(f"/ui/login?{query}").text
    assert "Call this number" not in page
    assert "anything you like" not in page
    assert (shown in page) if shown else ('class="notice' not in page)


@pytest.mark.parametrize(
    ("next", "lands"),
    [("/ui", "/ui"), ("//evil.example/ui", "/ui"), ("https://evil.example", "/ui")],
)
def test_after_sign_in_only_pages_of_the_ui(
    app_client: TestClient, services: Services, next: str, lands: str
) -> None:
    answer = try_sign_in(app_client, *browser_admin(services), next=next)
    assert answer.headers["location"] == lands


def test_a_user_signs_in_with_its_rights(
    app_client: TestClient, services: Services, account_id: str
) -> None:
    sign_in(
        app_client,
        *browser_user(services, Grant(accounts=[account_id], allow=["mail.read"])),
    )
    page = app_client.get("/ui").text
    assert "Signed in as <strong>browser-" in page
    assert "mail.read" in page
    assert "reads and sends anywhere" not in page


def test_the_start_page_shows_whole_groups_and_single_operations(
    app_client: TestClient, services: Services, account_id: str
) -> None:
    sign_in(
        app_client,
        *browser_user(
            services, Grant(accounts=[account_id], allow=["mail.read", "send_draft"])
        ),
    )
    page = app_client.get("/ui").text
    assert '<span class="tag accent">mail.read</span>' in page
    assert '<span class="tag mono">send_draft</span>' in page
    # A single operation does not show as its whole group.
    assert '<span class="tag accent">send</span>' not in page


def test_an_admin_is_warned(ui: TestClient, account_id: str) -> None:
    assert "reads and sends anywhere" in ui.get("/ui").text


def test_the_overview_starts_with_the_user(
    app_client: TestClient, services: Services, account_id: str
) -> None:
    services.roles.create_role(ADMIN, "readers", [])
    name, password = browser_user(
        services, Grant(accounts=[account_id], allow=["mail.read"]), roles=["readers"]
    )
    sign_in(app_client, name, password)
    page = app_client.get("/ui").text
    assert "<h2>You</h2>" in page and "readers" in page
    assert "this is the first" in page
    # The account opens its mail. Its page needs get_account.
    assert f'href="/ui/accounts/{account_id}/mail"' in page
    assert f'href="/ui/accounts/{account_id}"' not in page
    # Without accounts.read, no service card.
    assert "<h2>Service</h2>" not in page

    again = TestClient(app_client.app)
    sign_in(again, name, password)
    assert "before this one" in again.get("/ui").text


def test_the_overview_shows_the_service_to_who_may_list_accounts(
    ui: TestClient, account_id: str
) -> None:
    page = ui.get("/ui").text
    assert "<h2>Service</h2>" in page
    assert "sync worker" in page


# --- the session ----------------------------------------------------------------------


def test_sign_out_needs_the_csrf_token(ui: TestClient) -> None:
    refused = ui.post("/ui/logout", data={"csrf_token": "forged"})
    assert refused.status_code == 403
    assert "Form expired" in refused.text
    assert ui.get("/ui").status_code == 200
    token = csrf_of(ui.get("/ui").text)
    answer = ui.post("/ui/logout", data={"csrf_token": token}, follow_redirects=False)
    assert answer.status_code == 303
    assert ui.get("/ui", follow_redirects=False).status_code == 303


def test_the_csrf_token_also_comes_as_a_header(ui: TestClient) -> None:
    token = csrf_of(ui.get("/ui").text)
    answer = ui.post(
        "/ui/logout", headers={"X-CSRF-Token": token}, follow_redirects=False
    )
    assert answer.status_code == 303


def test_a_disabled_user_is_signed_out(
    app_client: TestClient, services: Services, account_id: str
) -> None:
    name, password = browser_user(
        services, Grant(accounts=[account_id], allow=["mail.read"])
    )
    sign_in(app_client, name, password)
    assert app_client.get("/ui").status_code == 200
    user = services.auth.user_named(name)
    assert user is not None
    services.users.update_user(ADMIN, user.id, disabled=True)
    assert app_client.get("/ui", follow_redirects=False).status_code == 303


def test_a_password_set_by_someone_else_is_changed_first(
    app_client: TestClient, services: Services, account_id: str
) -> None:
    user = services.users.create_user(
        ADMIN,
        "Anna",
        [],
        [Grant(accounts=[account_id], allow=["mail.read"])],
        ui_sign_in=True,
    )
    other = TestClient(app_client.app)
    sign_in(other, *browser_admin(services))
    set_to = "a password set by the admin"
    answer = post(
        other,
        f"/ui/users/{user.id}/password",
        {"new_password": set_to, "repeat_password": set_to},
    )
    assert "must be changed at the next sign-in" in answer.text
    assert set_to not in answer.text

    landed = try_sign_in(app_client, "anna", set_to)
    assert landed.headers["location"] == "/ui/password"
    # Every other page leads there first, until it is changed.
    assert app_client.get("/ui/mail", follow_redirects=False).headers["location"] == (
        "/ui/password"
    )
    page = app_client.get("/ui/password").text
    assert "Choose one of your own" in page
    mine = "my own long passphrase"
    changed = post(
        app_client,
        "/ui/password",
        {
            "current_password": set_to,
            "new_password": mine,
            "repeat_password": mine,
        },
    )
    assert "Password changed." in changed.text
    assert app_client.get("/ui/mail").status_code == 200
    try_sign_in(TestClient(app_client.app), "Anna", mine)


def test_a_changed_password_signs_out_the_other_sessions(
    app_client: TestClient, services: Services
) -> None:
    name, password = browser_admin(services)
    sign_in(app_client, name, password)
    laptop = TestClient(app_client.app)
    sign_in(laptop, name, password)
    new = "a brand new long passphrase"
    changed = post(
        app_client,
        "/ui/password",
        {"current_password": password, "new_password": new, "repeat_password": new},
    )
    assert "Other sessions are signed out." in changed.text
    assert app_client.get("/ui").status_code == 200
    assert laptop.get("/ui", follow_redirects=False).status_code == 303


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"current_password": "wrong", "new_password": "n" * 20}, "not right"),
        ({"new_password": "short"}, "at least 15"),
    ],
)
def test_a_password_change_that_fails_says_why(
    app_client: TestClient,
    services: Services,
    fields: dict[str, str],
    message: str,
) -> None:
    name, password = browser_admin(services)
    sign_in(app_client, name, password)
    data = {"current_password": password, **fields}
    data["repeat_password"] = data["new_password"]
    answer = post(app_client, "/ui/password", data)
    assert message in answer.text
    assert password not in answer.text and data["new_password"] not in answer.text
    differ = post(
        app_client,
        "/ui/password",
        {
            "current_password": password,
            "new_password": "n" * 20,
            "repeat_password": "x",
        },
    )
    assert "The two new passwords differ." in differ.text


def test_an_idle_session_expires() -> None:
    now = [NOW]
    store = SessionStore(clock=lambda: now[0])
    session_id = store.create(SIGNED)
    now[0] += IDLE - timedelta(minutes=1)
    assert store.get(session_id) is not None
    now[0] += IDLE + timedelta(minutes=1)
    assert store.get(session_id) is None
    assert store.get(session_id) is None
    assert store.get(None) is None


def test_the_idle_time_comes_from_the_settings(services: Services) -> None:
    now = [NOW]
    store = SessionStore(clock=lambda: now[0], idle=timedelta(minutes=5))
    session_id = store.create(SIGNED)
    now[0] += timedelta(minutes=6)
    assert store.get(session_id) is None
    settings = Settings(storage="memory", session_idle_hours=0.5)
    app = create_app(settings, services)
    assert app.state.ui_sessions.idle == timedelta(minutes=30)


def test_idle_sessions_are_swept_on_sign_in() -> None:
    now = [NOW]
    store = SessionStore(clock=lambda: now[0])
    forgotten = store.create(SIGNED)
    now[0] += IDLE + timedelta(minutes=1)
    fresh = store.create(SIGNED)
    assert len(store) == 1
    assert store.get(fresh) is not None
    assert store.get(forgotten) is None
