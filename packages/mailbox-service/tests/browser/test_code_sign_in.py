"""The sign-in with a code, the one page that runs htmx: it asks the
service every few seconds by itself and goes on once the person signed
in at the provider."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from playwright.sync_api import Page, expect

from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.models import Discovery

from ..conftest import browser_admin
from ..oauth_fake import PENDING, TokenEndpoint, code, services_with, signed_in
from .conftest import apart, served, sign_in, violations


class NothingFound:
    """Discovery without the network: an address at a domain no source
    knows, as a custom domain at Microsoft is. The page then offers the
    sign-in with the provider."""

    async def discover(self, caller: Any, email: str) -> Discovery:
        return Discovery(email=email, domain="example.org")


def test_the_code_page_goes_on_by_itself(
    page: Page, settings: Settings, master_key: None
) -> None:
    """No click after the code: htmx asks until the sign-in arrives, then
    follows HX-Redirect to the new account."""
    endpoint = TokenEndpoint(code(interval=1), PENDING, signed_in())
    services = replace(services_with(endpoint), discovery=NothingFound())
    with served(settings, services) as base:
        sign_in(page, base, *apart(browser_admin, services))
        page.goto(f"{base}/ui/accounts/new")
        page.fill(
            'form[action="/ui/accounts/discover"] input[name="email"]', "me@example.org"
        )
        page.click('form[action="/ui/accounts/discover"] button[type="submit"]')
        page.click('form[action="/ui/oauth/microsoft/device"] button')
        expect(page.locator("#user-code")).to_have_text("ABCD-EFGH")
        assert violations(page) == []
        page.wait_for_url(
            lambda url: "/ui/accounts/" in url and "/new" not in url, timeout=30_000
        )
        [account_id] = services.adapters.ids()
        assert page.url == f"{base}/ui/accounts/{account_id}"
        expect(page.get_by_text("me@example.org signed in.")).to_be_visible()
    # The code, then two polls: one still pending, one signed in.
    assert len(endpoint.forms) == 3
