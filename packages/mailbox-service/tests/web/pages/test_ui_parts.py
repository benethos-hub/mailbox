"""The parts every page shares (docs/UI.md 7): the icons and the script
that picks them, the question before a form, copying a secret, times in
lists, and that nothing is loaded from elsewhere."""

from __future__ import annotations

import importlib.util
import re
from datetime import timedelta
from pathlib import Path
from types import ModuleType

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service.common.clock import utc_now
from benethos_mailbox_service.web.pages.templates import (
    STATIC_DIR,
    TEMPLATE_DIR,
    ago,
    when,
)

from ...ui_helpers import post

REPOSITORY = Path(__file__).resolve().parents[5]
SPRITE = "/ui/static/img/icons.svg"


def _icons() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "assets_icons", REPOSITORY / "assets" / "icons.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _held() -> set[str]:
    return set(_icons().names((STATIC_DIR / "img/icons.svg").read_text("utf-8")))


# --- the icons ------------------------------------------------------------------------


def test_the_sprite_holds_the_icons_the_script_names() -> None:
    # After a change of ICONS: uv run python assets/icons.py
    icons = _icons()
    assert icons.main(["--check"]) == 0
    sprite = icons.SPRITE.read_text("utf-8")
    assert f"Bootstrap Icons {icons.VERSION}, MIT licence" in sprite
    assert "<script" not in sprite and "style=" not in sprite
    assert "MIT License" in icons.LICENSE.read_text("utf-8")


def test_an_icon_of_another_shape_is_refused() -> None:
    with pytest.raises(ValueError, match="expected shape"):
        _icons().symbol("x", "<svg><path/></svg>")


def test_the_script_turns_an_icon_into_a_symbol() -> None:
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16"'
        ' fill="currentColor" class="bi bi-plus" viewBox="0 0 16 16">\n'
        '  <path d="M8 4"/>\n  <path d="M1 1"/>\n</svg>'
    )
    made = _icons().symbol("plus", svg)
    assert made == (
        '<symbol id="plus" viewBox="0 0 16 16">'
        '<path d="M8 4"/> <path d="M1 1"/></symbol>'
    )


PAGES = (
    "/ui",
    "/ui/accounts",
    "/ui/accounts/{account_id}",
    "/ui/accounts/{account_id}/mail",
    "/ui/users",
    "/ui/roles",
    "/ui/webhooks",
    "/ui/second-factor",
    "/ui/sends",
)


def test_every_icon_a_page_shows_is_in_the_sprite(
    ui: TestClient, account_id: str
) -> None:
    held = _held()
    shown: set[str] = set()
    for page in PAGES:
        text = ui.get(page.format(account_id=account_id)).text
        shown |= set(re.findall(r'icons\.svg#([\w-]+)"', text))
    assert {"house", "plus-lg", "envelope"} <= shown
    assert shown - held == set()


# The icon of a link_button: its name is lower case, a word on a button
# is not.
LINK_ICON = r'link_button\([^\n]*?"([a-z][a-z0-9-]*)"(?:, cls="\w*")?\)'


def test_every_icon_a_template_or_the_script_names_is_in_the_sprite() -> None:
    named = {"clipboard-check"}  # app.js shows it once a secret is copied
    for template in TEMPLATE_DIR.rglob("*.html"):
        text = template.read_text("utf-8")
        named |= set(re.findall(r'\bicon(?:=|\()"([\w-]+)"', text))
        named |= set(re.findall(LINK_ICON, text))
    navigation = (TEMPLATE_DIR.parent / "navigation.py").read_text("utf-8")
    named |= set(re.findall(r'Entry\("\w+", "[^"]+", "([\w-]+)"', navigation))
    assert len(named) > 10
    assert named - _held() == set()


def _new_token(ui: TestClient) -> str:
    """The page of the admin's own user, right after it made a token."""
    user = re.search(r'href="(/ui/users/usr_\w+)"', ui.get("/ui/users").text)
    assert user is not None
    made = post(ui, user.group(1) + "/tokens", {"name": "laptop", "days": ""})
    return made.text


def test_a_secret_shown_once_has_a_copy_button(ui: TestClient) -> None:
    copy = re.search(
        r'<code class="secret" id="secret">[^<]+</code><button class="small icon-btn"'
        r' type="button" data-copy="secret" title="Copy" aria-label="Copy">(.*?)'
        r"</button>",
        _new_token(ui),
    )
    assert copy is not None
    assert '<svg class="i" aria-hidden="true" focusable="false">' in copy.group(1)


# --- the question before a form -------------------------------------------------------


def test_every_page_has_the_dialog_that_asks(ui: TestClient) -> None:
    page = ui.get("/ui").text
    assert '<dialog class="ask" id="confirm" aria-labelledby="confirm-title">' in page
    assert '<form method="dialog">' in page
    assert '<div class="toast" id="toast" role="status" hidden></div>' in page


def test_a_red_button_asks_with_its_own_word(ui: TestClient) -> None:
    page = post(ui, "/ui/users", {"name": "bert", "signs_in_to": "api"}).text
    assert (
        'data-confirm="Delete bert and its tokens?" data-confirm-label="Delete user"'
        " data-confirm-danger>" in page
    )


def test_the_script_asks_without_the_browsers_confirm_where_it_can() -> None:
    script = (STATIC_DIR / "js/app.js").read_text("utf-8")
    assert "showModal" in script and "requestSubmit" in script
    assert "navigator.clipboard" in script and '"/"' in script


# --- times in lists -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("before", "shown"),
    [
        (timedelta(seconds=20), "just now"),
        (timedelta(minutes=1, seconds=5), "1 minute ago"),
        (timedelta(minutes=42), "42 minutes ago"),
        (timedelta(hours=1), "1 hour ago"),
        (timedelta(hours=23, minutes=59), "23 hours ago"),
    ],
)
def test_a_time_under_a_day_ago_is_told_relative(before: timedelta, shown: str) -> None:
    assert ago(utc_now() - before) == shown


def test_an_older_or_a_coming_time_is_told_as_date_and_time() -> None:
    old, coming = utc_now() - timedelta(days=2), utc_now() + timedelta(hours=1)
    assert ago(old) == when(old)
    assert ago(coming) == when(coming)
    assert ago(None) == "—"


def test_a_relative_time_has_the_full_stamp_as_tooltip(ui: TestClient) -> None:
    found = re.search(
        r'<time datetime="[^"]+" title="\d{4}-\d\d-\d\d \d\d:\d\d">just now</time>',
        _new_token(ui),
    )
    assert found is not None


# --- nothing from elsewhere -----------------------------------------------------------


def test_nothing_is_loaded_from_elsewhere() -> None:
    """No CDN: every script, style, font and image the UI loads is under
    static/ (docs/UI.md 8)."""
    loaded = re.compile(r'\b(?:src|href|srcset)="(?:https?:)?//', re.I)
    imported = re.compile(r"@import|url\(\s*['\"]?(?:https?:)?//", re.I)
    found = [
        t.name
        for t in TEMPLATE_DIR.rglob("*.html")
        if loaded.search(t.read_text("utf-8"))
    ]
    found += [
        s.name
        for s in STATIC_DIR.rglob("*.css")
        if imported.search(s.read_text("utf-8"))
    ]
    assert found == []
