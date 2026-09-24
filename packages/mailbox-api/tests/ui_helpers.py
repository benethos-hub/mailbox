"""Using the configuration UI the way a browser does."""

from __future__ import annotations

import re

import httpx
from fastapi.testclient import TestClient

from .conftest import API_KEY


def sign_in(client: TestClient, token: str = API_KEY, next: str = "/ui") -> None:
    page = client.get("/ui/login")
    nonce = re.search(r'name="nonce" value="([^"]+)"', page.text)
    assert nonce is not None
    answer = client.post(
        "/ui/login",
        data={"token": token, "nonce": nonce.group(1), "next": next},
        follow_redirects=False,
    )
    assert answer.status_code == 303, answer.text


def csrf_of(html: str) -> str:
    found = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert found is not None
    return found.group(1)


def post(
    client: TestClient,
    url: str,
    data: dict[str, str] | None = None,
    follow_redirects: bool = True,
) -> httpx.Response:
    """A form post from a page of the UI, with the session's CSRF token."""
    token = csrf_of(client.get("/ui").text)
    return client.post(
        url,
        data={"csrf_token": token, **(data or {})},
        follow_redirects=follow_redirects,
    )
