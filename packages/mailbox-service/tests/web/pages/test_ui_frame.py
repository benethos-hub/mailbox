"""The configuration UI: the frame, static files, colours and templates."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.data.models import Grant
from benethos_mailbox_service.web.pages.templates import STATIC_DIR, TEMPLATE_DIR

from ...conftest import browser_user
from ...ui_helpers import sign_in

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
        ("on-accent", "bad"),
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
