"""The configuration UI in real browsers: Chrome, Firefox and WebKit through
Playwright, against the real app served by uvicorn on 127.0.0.1.

pytest and the live checks run no JavaScript, so only these tests see htmx
work and the content security policy hold. The default run leaves this
folder out (``collect_ignore`` in the conftest above). CI's browser job runs
it with the browser dependency group and MAILBOX_BROWSER_TESTS=1."""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from typing import Any, TypeVar

import pytest
import uvicorn
from playwright.sync_api import Browser, Page, Playwright, sync_playwright

from benethos_mailbox_service.assembly import Services, create_app
from benethos_mailbox_service.config import Settings

BROWSERS = ("chromium", "firefox", "webkit")

T = TypeVar("T")


def apart(fn: Callable[..., T], *args: Any) -> T:
    """``fn`` in a thread of its own. Playwright keeps an event loop running
    in the test's thread, where the helpers that call asyncio.run fail,
    such as the one that makes a user."""
    with ThreadPoolExecutor(1) as pool:
        return pool.submit(fn, *args).result()


# Each violation of the content security policy, kept in the page. The
# event names the directive, which the console message of WebKit does not.
_RECORD = """
window.__violations = [];
document.addEventListener('securitypolicyviolation', e => {
  window.__violations.push(e.effectiveDirective + ' ' + e.blockedURI);
});
"""


@pytest.fixture(scope="session")
def playwright() -> Iterator[Playwright]:
    with sync_playwright() as running:
        yield running


@pytest.fixture(scope="session", params=BROWSERS)
def browser(
    request: pytest.FixtureRequest, playwright: Playwright
) -> Iterator[Browser]:
    launched = getattr(playwright, request.param).launch()
    yield launched
    launched.close()


@pytest.fixture
def page(browser: Browser) -> Iterator[Page]:
    """A fresh page that records violations of the content security
    policy: no cookies of another test."""
    context = browser.new_context()
    context.add_init_script(_RECORD)
    opened = context.new_page()
    yield opened
    context.close()


def violations(page: Page) -> list[str]:
    """The violations of the content security policy on the page shown."""
    found: list[str] = page.evaluate("window.__violations || []")
    return found


@contextmanager
def served(settings: Settings, services: Services) -> Iterator[str]:
    """The app of ``services`` on a free port of 127.0.0.1, and its
    address."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    config = uvicorn.Config(create_app(settings, services), log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(
        target=server.run, kwargs={"sockets": [sock]}, daemon=True
    )
    thread.start()
    try:
        deadline = time.monotonic() + 15
        while not server.started:
            if not thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("the app did not start")
            time.sleep(0.05)
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(15)
        sock.close()


def sign_in(page: Page, base: str, name: str, password: str) -> None:
    """The sign-in form, filled and sent as a person does."""
    page.goto(f"{base}/ui/login")
    page.fill("#f-name", name)
    page.fill("#f-password", password)
    page.click('form[action="/ui/login"] button[type="submit"]')
    page.wait_for_url(f"{base}/ui")
