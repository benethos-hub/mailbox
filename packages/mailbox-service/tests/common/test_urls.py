"""Where a URL points, and what of it goes on."""

from __future__ import annotations

import pytest

from benethos_mailbox_service.common.urls import host_of, is_loopback, path_and_query


@pytest.mark.parametrize(
    ("url", "host"),
    [
        ("https://Hooks.Example.org:8443/x?key=secret", "hooks.example.org"),
        ("http://[::1]:8080/", "::1"),
        ("not a url", None),
        ("http://[::1/", None),
        ("", None),
    ],
)
def test_the_host_of_a_url(url: str, host: str | None) -> None:
    assert host_of(url) == host


@pytest.mark.parametrize(
    ("url", "loopback"),
    [
        ("http://localhost:8080/ui/oauth/microsoft/callback", True),
        ("http://LOCALHOST/", True),
        ("http://127.0.0.2/", True),
        ("http://[::1]:8080/", True),
        ("https://mail.example.org/", False),
        ("http://10.0.0.1/", False),
        ("http://[::1/", False),
    ],
)
def test_a_loopback_url(url: str, loopback: bool) -> None:
    assert is_loopback(url) is loopback


@pytest.mark.parametrize(
    ("url", "rest"),
    [
        ("https://jmap.example.org/api/?a=b", "/api/?a=b"),
        ("https://jmap.example.org/api/", "/api/"),
        ("/ui/accounts?cursor=x", "/ui/accounts?cursor=x"),
        ("", ""),
    ],
)
def test_the_path_and_query(url: str, rest: str) -> None:
    assert path_and_query(url) == rest
