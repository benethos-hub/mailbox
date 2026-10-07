"""The configuration UI: signing in, the session, CSRF, the frame."""

from __future__ import annotations

import re
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service.assembly import Services, create_app
from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.models import Grant
from benethos_mailbox_service.domain.auth.service import SignedIn
from benethos_mailbox_service.web.pages.session import IDLE, SessionStore
from benethos_mailbox_service.web.pages.templates import STATIC_DIR, TEMPLATE_DIR

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
    services.users.create_role(ADMIN, "readers", [])
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


# --- the frame ------------------------------------------------------------------------


def test_the_sidebar_shows_what_the_user_may_open(
    app_client: TestClient, services: Services, account_id: str
) -> None:
    sign_in(
        app_client,
        *browser_user(services, Grant(accounts=[account_id], allow=["mail.read"])),
    )
    page = app_client.get("/ui").text
    assert 'href="/ui/mail"' in page
    for hidden in ("/ui/accounts", "/ui/sends", "/ui/users", "/ui/roles"):
        assert f'href="{hidden}"' not in page, hidden
    assert ">Service<" not in page
    # Without users.manage the name is no link to a page it cannot open.
    assert "Signed in as <strong>browser-" in page


def test_the_admin_sees_every_entry_and_its_own_page(ui: TestClient) -> None:
    page = ui.get("/ui/users").text
    for entry in ("/ui/accounts", "/ui/sends", "/ui/users", "/ui/roles"):
        assert f'href="{entry}"' in page, entry
    assert 'href="/ui/users" class="active" aria-current="page"' in page
    assert re.search(r'Signed in as <a href="/ui/users/usr_\w+"><strong>admin', page)


def test_security_headers_on_the_ui_only(ui: TestClient, client: TestClient) -> None:
    page = ui.get("/ui")
    policy = page.headers["content-security-policy"]
    assert "script-src 'self'" in policy and "frame-ancestors 'none'" in policy
    assert page.headers["cache-control"] == "no-store"
    assert "content-security-policy" not in client.get("/v1/me").headers


def test_static_files_are_kept_and_asked_again(ui: TestClient) -> None:
    first = ui.get("/ui/static/css/app.css")
    assert first.headers["cache-control"] == "no-cache"
    again = ui.get(
        "/ui/static/css/app.css", headers={"if-none-match": first.headers["etag"]}
    )
    assert again.status_code == 304


def test_no_inline_script(ui: TestClient) -> None:
    page = ui.get("/ui").text
    assert (
        "<script>" not in page and " onsubmit=" not in page and " onclick=" not in page
    )


def test_static_files(app_client: TestClient) -> None:
    for path in (
        "/ui/static/css/app.css",
        "/ui/static/js/app.js",
        "/ui/static/vendor/htmx/htmx.min.js",
    ):
        assert app_client.get(path).status_code == 200, path


def test_errors_in_the_ui_are_pages(ui: TestClient, client: TestClient) -> None:
    missing = ui.get("/ui/nothing-here")
    assert missing.status_code == 404
    assert "text/html" in missing.headers["content-type"]
    assert client.get("/v1/nothing-here").json()["error"]["code"] == "not_found"


def test_an_incomplete_form_is_a_page(app_client: TestClient) -> None:
    answer = app_client.get("/ui/login", params={"minutes": "soon"})
    assert answer.status_code == 400
    assert "Incomplete form" in answer.text


def test_the_ui_is_not_in_the_contract(client: TestClient) -> None:
    assert not [p for p in client.get("/openapi.json").json()["paths"] if "/ui" in p]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("/ui/accounts?x=1", "/ui/accounts?x=1"),
        ("/ui", "/ui"),
        ("https://evil.example/ui/x", "/ui/fallback"),
        ("//evil.example/ui", "/ui/fallback"),
        ("/uievil", "/ui/fallback"),
        ("/v1/me", "/ui/fallback"),
        ("", "/ui/fallback"),
        (None, "/ui/fallback"),
    ],
)
def test_only_local_paths_after_a_form(value: str | None, expected: str) -> None:
    from benethos_mailbox_service.web.pages.templates import local_path

    assert local_path(value, "/ui/fallback") == expected


def test_page_links_carry_the_query_and_quote_the_cursor() -> None:
    from starlette.requests import Request

    from benethos_mailbox_service.web.pages.templates import page_links

    def request(query: str) -> Request:
        return Request(
            {
                "type": "http",
                "path": "/ui/x",
                "query_string": query.encode(),
                "headers": [],
            }
        )

    more, first = page_links(request("q=a"), "c+d/e=")
    assert more == "/ui/x?q=a&cursor=c%2Bd%2Fe%3D" and first is None
    more, first = page_links(request("q=a&cursor=old"), None)
    assert more is None and first == "/ui/x?q=a"
    assert page_links(request("cursor=old"), None) == (None, "/ui/x")


def _tokens(block: str) -> dict[str, str]:
    return dict(re.findall(r"--([a-z0-9-]+):\s*(#[0-9a-f]{6});", block))


def _contrast(a: str, b: str) -> float:
    def luminance(colour: str) -> float:
        parts = [int(colour[i : i + 2], 16) / 255 for i in (1, 3, 5)]
        r, g, b = (
            p / 12.92 if p <= 0.03928 else ((p + 0.055) / 1.055) ** 2.4 for p in parts
        )
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    light, dark = sorted((luminance(a), luminance(b)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def test_every_text_colour_is_readable_on_its_backgrounds() -> None:
    """WCAG AA for small text, 4.5:1, in light and in dark mode."""
    from benethos_mailbox_service.web.pages.templates import STATIC_DIR

    css = (STATIC_DIR / "css" / "app.css").read_text(encoding="utf-8")
    light = _tokens(css[: css.index("@media (prefers-color-scheme: dark)")])
    dark = {**light, **_tokens(css[css.index("@media (prefers-color-scheme: dark)") :])}
    texts = ("text", "text-muted", "text-faint", "accent", "ok", "bad", "warn")
    pairs = [(t, b) for t in texts for b in ("bg", "surface", "surface-2")] + [
        ("on-accent", "accent"),
        ("accent", "accent-soft"),
        ("ok", "ok-soft"),
        ("bad", "err-soft"),
        ("warn", "warn-soft"),
    ]
    for mode, tokens in (("light", light), ("dark", dark)):
        for text, background in pairs:
            ratio = _contrast(tokens[text], tokens[background])
            assert ratio >= 4.5, f"{mode}: {text} on {background} is {ratio:.2f}:1"


@pytest.mark.parametrize(
    ("page", "back"),
    [
        ("/ui/accounts/new", "/ui/accounts"),
        ("/ui/users/new", "/ui/users"),
        ("/ui/roles/new", "/ui/roles"),
        ("/ui/webhooks/new", "/ui/webhooks"),
        ("/ui/accounts/{account_id}/compose", "/ui/accounts/{account_id}/mail"),
    ],
)
def test_every_editor_has_a_way_back(
    ui: TestClient, account_id: str, page: str, back: str
) -> None:
    """docs/UI.md 4.3: an editor page has Cancel back where it came from."""
    text = ui.get(page.format(account_id=account_id)).text
    assert (
        f'<a class="btn" href="{back.format(account_id=account_id)}">Cancel</a>' in text
    )


def test_every_class_a_template_names_is_styled() -> None:
    """A class without a rule in app.css is a leftover or a typo, as the
    hidden "Select" heading of the mail list once was."""
    css = (STATIC_DIR / "css" / "app.css").read_text(encoding="utf-8")
    styled = set(re.findall(r"\.([a-zA-Z][\w-]*)", css))
    unstyled = set()
    for template in TEMPLATE_DIR.rglob("*.html"):
        text = template.read_text(encoding="utf-8")
        # Only fixed classes: one computed by the template is left out.
        for names in re.findall(r'class="([^"{}]*)"', text):
            unstyled |= {
                f"{template.name}: {n}" for n in names.split() if n not in styled
            }
    assert not unstyled, sorted(unstyled)


def test_no_template_marks_text_as_safe() -> None:
    """Everything a page shows is escaped. Markup a card needs comes from a
    macro, never from a string marked safe."""
    marked = [
        template.name
        for template in TEMPLATE_DIR.rglob("*.html")
        if re.search(r"\|\s*safe\b", template.read_text(encoding="utf-8"))
    ]
    assert marked == []
