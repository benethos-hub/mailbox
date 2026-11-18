"""Passkeys in a real browser: the script hands the options to WebAuthn,
a virtual authenticator of Chromium makes and signs the passkey, and the
answer signs in after the password (docs/AUTHENTICATION.md 4, 5).

Only Chromium offers a virtual authenticator, through its DevTools
protocol, so this test runs in Chromium alone. The service is reached
at localhost: browsers make no passkey for an address."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from playwright.sync_api import Page, Playwright, expect

from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.models import ActivityFilter, Grant

from ..conftest import ADMIN, browser_user
from .conftest import _RECORD, apart, served, violations

READER = Grant(accounts=["*"], allow=["mail.read"])


@pytest.fixture
def chromium(playwright: Playwright) -> Iterator[Page]:
    """A page of Chromium with a virtual authenticator that holds
    passkeys, verifies its user and needs no touch."""
    browser = playwright.chromium.launch()
    context = browser.new_context()
    context.add_init_script(_RECORD)
    page = context.new_page()
    devtools = context.new_cdp_session(page)
    devtools.send("WebAuthn.enable")
    devtools.send(
        "WebAuthn.addVirtualAuthenticator",
        {
            "options": {
                "protocol": "ctap2",
                "transport": "internal",
                "hasResidentKey": True,
                "hasUserVerification": True,
                "isUserVerified": True,
                "automaticPresenceSimulation": True,
            }
        },
    )
    yield page
    browser.close()


def test_a_passkey_is_made_and_signs_in(
    master_key: None, chromium: Page, settings: Settings, services: Services
) -> None:
    page = chromium
    services.vault.initialize()
    name, password = apart(browser_user, services, READER)
    # Two sign-ins in a few seconds pass the brake on unknown callers.
    unlimited = settings.model_copy(update={"rate_limit_anonymous_per_minute": 0})
    with served(unlimited, services) as served_at:
        base = served_at.replace("127.0.0.1", "localhost")
        page.goto(f"{base}/ui/login")
        page.fill("#f-name", name)
        page.fill("#f-password", password)
        page.click('form[action="/ui/login"] button[type="submit"]')
        page.wait_for_url(f"{base}/ui")

        page.goto(f"{base}/ui/second-factor")
        page.click('button[data-toggle="add-passkey"]')
        page.fill("#f-passkey-name", "Laptop")
        page.fill("#f-passkey-password", password)
        page.click('form[action="/ui/second-factor/passkeys/begin"] button.primary')
        make = page.locator("button[data-passkey-create]")
        expect(make).to_be_visible()
        make.click()
        expect(page.get_by_text("Second factor on.")).to_be_visible()
        expect(page.locator("#recovery-codes li")).to_have_count(10)
        expect(page.locator('td.name:text-is("Laptop")')).to_be_visible()
        assert violations(page) == []

        page.context.clear_cookies()
        page.goto(f"{base}/ui/login")
        page.fill("#f-name", name)
        page.fill("#f-password", password)
        page.click('form[action="/ui/login"] button[type="submit"]')
        page.wait_for_url(f"{base}/ui/login/code")
        page.click("button[data-passkey-use]")
        page.wait_for_url(f"{base}/ui")
        assert violations(page) == []
    found = services.audit.list_activity(
        ADMIN, limit=10, matching=ActivityFilter(activity="auth.signed_in")
    )
    assert [record.credential for record in found.items][0] == "password+passkey"
