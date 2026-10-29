"""Using the configuration UI the way a browser does."""

from __future__ import annotations

import re
from typing import Any

import httpx
from fastapi.testclient import TestClient

from benethos_mailbox_service.assembly import Services, create_app
from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.models import Grant

from .conftest import browser_admin, browser_user


def signed_in(services: Services, *grants: Grant) -> TestClient:
    """A browser signed in to the UI of ``services``: as a user with
    ``grants``, without them as the admin."""
    client = TestClient(create_app(Settings(storage="memory"), services))
    who = browser_user(services, *grants) if grants else browser_admin(services)
    sign_in(client, *who)
    return client


def sign_in(client: TestClient, name: str, password: str, next: str = "/ui") -> None:
    answer = try_sign_in(client, name, password, next)
    assert answer.status_code == 303, answer.text
    assert "notice=" not in answer.headers["location"], answer.headers["location"]


def try_sign_in(
    client: TestClient, name: str, password: str, next: str = "/ui"
) -> httpx.Response:
    """The sign-in form sent the way a browser sends it, not followed."""
    page = client.get("/ui/login")
    nonce = re.search(r'name="nonce" value="([^"]+)"', page.text)
    assert nonce is not None
    return client.post(
        "/ui/login",
        data={
            "name": name,
            "password": password,
            "nonce": nonce.group(1),
            "next": next,
        },
        follow_redirects=False,
    )


def csrf_of(html: str) -> str:
    found = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert found is not None
    return found.group(1)


def post(
    client: TestClient,
    url: str,
    data: dict[str, Any] | None = None,
    follow_redirects: bool = True,
) -> httpx.Response:
    """A form post from a page of the UI, with the session's CSRF token."""
    token = csrf_of(client.get("/ui").text)
    return client.post(
        url,
        data={"csrf_token": token, **(data or {})},
        follow_redirects=follow_redirects,
    )
