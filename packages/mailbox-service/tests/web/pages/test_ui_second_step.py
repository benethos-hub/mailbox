"""How the second step of a form looks on the pages: a named group, its
methods, the list of the others (docs/UI.md 6.3)."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service.assembly import Services

from ...conftest import UI_PASSWORD, browser_admin
from ...ui_helpers import post, try_sign_in
from .factor_page_helpers import code_form, with_factor

pytestmark = pytest.mark.usefixtures("master_key")


@pytest.fixture
def factor_on(
    master_key: None, app_client: TestClient, services: Services
) -> list[str]:
    """An administrator with the device Phone, signed in with a recovery
    code: the codes left."""
    services.vault.initialize()
    name, password = browser_admin(services)
    _, codes = with_factor(services, name)
    try_sign_in(app_client, name, password)
    code_form(app_client, codes[0])
    return codes[1:]


@pytest.mark.usefixtures("factor_on")
def test_the_step_is_a_named_group(app_client: TestClient) -> None:
    page = app_client.get("/ui/second-factor").text
    assert '<fieldset class="factor-step" data-ways>' in page
    assert "<legend>Confirm it is you</legend>" in page
    assert (
        '<fieldset class="factor-step" data-ways>'
        in app_client.get("/ui/password").text
    )


def test_the_code_page_names_the_step_to_a_screen_reader(
    app_client: TestClient, services: Services
) -> None:
    services.vault.initialize()
    name, password = browser_admin(services)
    with_factor(services, name)
    try_sign_in(app_client, name, password)
    page = app_client.get("/ui/login/code").text
    assert '<legend class="sr">Confirm it is you</legend>' in page


@pytest.mark.usefixtures("factor_on")
def test_a_code_field_shows_the_form_of_a_code(app_client: TestClient) -> None:
    page = app_client.get("/ui/second-factor").text
    assert '<input id="f-codes-totp" class="code" name="code"' in page
    assert '<input id="f-codes-recovery" class="code" name="code"' in page
    assert 'placeholder="XXXXX-XXXXX-XXXXX"' in page


@pytest.mark.usefixtures("factor_on")
def test_the_list_of_the_methods_says_what_each_is(app_client: TestClient) -> None:
    page = app_client.get("/ui/password").text
    assert 'aria-expanded="false" aria-controls="f-password-ways"' in page
    assert 'id="f-password-ways" role="group"' in page
    assert 'aria-labelledby="f-password-ways-label"' in page
    assert "Choose how to confirm" in page
    assert "The 6-digit code the app shows now" in page
    assert "One of the codes you saved. Each works once." in page


@pytest.mark.usefixtures("factor_on")
def test_the_answer_of_the_browser_is_a_notice(app_client: TestClient) -> None:
    page = app_client.get("/ui/second-factor").text
    assert (
        '<p class="notice warn factor-status" data-passkey-status role="status" hidden>'
        in page
    )


@pytest.mark.usefixtures("factor_on")
def test_a_refused_dialog_opens_again_with_the_reason(app_client: TestClient) -> None:
    refused = post(
        app_client, "/ui/second-factor/codes", {"password": "wrong", "code": "000000"}
    )
    page = refused.text
    opened = page.index('aria-describedby="new-codes-text" data-open>')
    reason = page.index('<div class="notice err" role="alert">')
    assert opened < reason
    assert page.count('class="notice err"') == 1
    # Once: the next page opens nothing.
    assert "data-open" not in app_client.get("/ui/second-factor").text


@pytest.mark.parametrize(
    ("code", "first"), [("000 000", "totp"), ("AAAAA-AAAAA-AAAAA", "recovery")]
)
def test_after_a_wrong_code_its_field_shows_first(
    app_client: TestClient, services: Services, code: str, first: str
) -> None:
    services.vault.initialize()
    name, password = browser_admin(services)
    with_factor(services, name)
    try_sign_in(app_client, name, password)
    page = app_client.get("/ui/login/code").text
    nonce = re.search(r'name="nonce" value="([^"]+)"', page)
    assert nonce is not None
    wrong = app_client.post(
        "/ui/login/code",
        data={"code": code, "nonce": nonce.group(1)},
        follow_redirects=False,
    )
    assert wrong.headers["location"].startswith("/ui/login/code?wrong=1&code=")
    again = app_client.get(wrong.headers["location"]).text
    assert f'data-ways-first="{first}"' in again
    assert "data-ways-first" not in app_client.get("/ui/login/code").text


def test_the_page_says_whether_the_factor_is_on(
    app_client: TestClient, services: Services
) -> None:
    services.vault.initialize()
    name, password = browser_admin(services)
    try_sign_in(app_client, name, password)
    off = app_client.get("/ui/second-factor").text
    assert '<span class="tag warn">off</span> Your password alone' in off
    _, codes = with_factor(services, name)
    try_sign_in(app_client, name, password)
    code_form(app_client, codes[0])
    on = app_client.get("/ui/second-factor").text
    assert '<span class="tag ok">on</span> Signing in to this UI' in on
    assert "A code from any of them works." in on
    assert "1 devices" not in on and "devices:" not in on


@pytest.mark.usefixtures("factor_on")
def test_new_recovery_codes_start_in_the_head_of_their_card(
    app_client: TestClient,
) -> None:
    page = app_client.get("/ui/second-factor").text
    card = re.search(r"<h2>Recovery codes</h2>(.*?)</section>", page, re.DOTALL)
    assert card is not None
    head, rest = card.group(1).split("</header>")
    assert 'data-dialog="new-codes"' in head
    # Nine codes left: no warning, so no body.
    assert rest.strip() == ""


def test_new_codes_and_their_card_have_titles_of_their_own(
    app_client: TestClient, factor_on: list[str]
) -> None:
    made = post(
        app_client,
        "/ui/second-factor/codes",
        {"password": UI_PASSWORD, "code": factor_on[0]},
    ).text
    assert made.count("<h2>Your new recovery codes</h2>") == 1
    assert made.count("<h2>Recovery codes</h2>") == 1


def test_the_setup_of_a_device_cancels_beside_its_button(
    app_client: TestClient, services: Services
) -> None:
    services.vault.initialize()
    name, password = browser_admin(services)
    try_sign_in(app_client, name, password)
    page = post(
        app_client,
        "/ui/second-factor/totp/begin",
        {"name": "Phone", "password": password},
    ).text
    assert '<form class="factor-setup"' in page
    assert '<button type="submit" form="totp-cancel">Cancel</button>' in page
    assert '<form id="totp-cancel" method="post"' in page
    assert "2. The 6-digit code Phone shows now" in page


@pytest.mark.usefixtures("factor_on")
def test_a_hint_belongs_to_its_field_and_a_text_to_its_dialog(
    app_client: TestClient,
) -> None:
    page = app_client.get("/ui/second-factor").text
    assert 'aria-describedby="f-codes-recovery-hint"' in page
    assert '<span class="hint" id="f-codes-recovery-hint">' in page
    assert 'aria-describedby="new-codes-text"' in page
    assert '<p id="new-codes-text">' in page


@pytest.mark.usefixtures("factor_on")
def test_the_count_of_a_card_is_told_from_its_description(
    app_client: TestClient,
) -> None:
    page = app_client.get("/ui/second-factor").text
    assert '<span class="meta count">1</span>' in page
    assert '<span class="meta">A code from any of them works.</span>' in page
