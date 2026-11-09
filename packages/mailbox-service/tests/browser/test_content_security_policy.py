"""Every page of the UI under its content security policy: no inline
script or style, nothing from elsewhere, and every file it loads found.
A page that breaks the policy works in no browser as written."""

from __future__ import annotations

from collections import deque
from urllib.parse import urlsplit

from playwright.sync_api import Browser, Error, Page

from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.models import ProviderType

from ..conftest import browser_admin, create_account
from .conftest import apart, served, sign_in, violations

# Enough to reach every kind of page from the overview. Links that differ
# in their query alone count once.
MAX_PAGES = 120
# Sign-out ends the session, an OAuth start leaves for the provider.
SKIPPED = ("/ui/logout", "/ui/oauth/")
# WebKit reports style-src-attr at each <select>, from a style of its own:
# a bare <select> on an empty page does it, and the select looks the same
# with the policy and without. Chrome and Firefox report every inline style
# attribute, so WebKit is held to the rest.
WEBKIT_OWN = "style-src-attr"


def test_no_page_breaks_the_policy(
    page: Page,
    browser: Browser,
    settings: Settings,
    services: Services,
) -> None:
    account_id = apart(
        create_account, services.accounts, ProviderType.MEMORY, "me@example.com"
    ).id
    # A file of the UI not found. Chrome aborts a stylesheet whose answer
    # is a page of HTML (nosniff), so a failed request counts as well.
    missing: list[str] = []
    page.on(
        "response",
        lambda answer: (
            missing.append(f"{answer.status} {answer.url}")
            if answer.status >= 400 and "/ui/static/" in answer.url
            else None
        ),
    )
    page.on(
        "requestfailed",
        lambda request: (
            missing.append(f"{request.failure} {request.url}")
            if "/ui/static/" in request.url
            else None
        ),
    )
    with served(settings, services) as base:
        sign_in(page, base, *apart(browser_admin, services))
        seen, broken = _crawl(page, base, browser.browser_type.name)
    assert f"/ui/accounts/{account_id}" in seen, sorted(seen)
    assert len(seen) >= 15, sorted(seen)
    assert broken == {}, broken
    assert missing == []


def _crawl(page: Page, base: str, engine: str) -> tuple[set[str], dict[str, list[str]]]:
    """Every page reached by links from the overview, and the violations on
    each that has some."""
    seen: set[str] = set()
    broken: dict[str, list[str]] = {}
    queue = deque(["/ui"])
    while queue and len(seen) < MAX_PAGES:
        href = queue.popleft()
        path = urlsplit(href).path
        if path in seen or path.startswith(SKIPPED):
            continue
        seen.add(path)
        try:
            page.goto(base + href)
        except Error as exc:
            # A link to a file starts a download instead of a page.
            if "Download is starting" in str(exc):
                continue
            raise
        found = [
            v
            for v in violations(page)
            if not (engine == "webkit" and v.startswith(WEBKIT_OWN))
        ]
        if found:
            broken[path] = found
        links: list[str] = page.eval_on_selector_all(
            'a[href^="/ui"]', "links => links.map(link => link.getAttribute('href'))"
        )
        queue.extend(link.split("#")[0] for link in links)
    return seen, broken
