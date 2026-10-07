"""Host names in one form."""

from __future__ import annotations

import pytest

from benethos_mailbox_service.common.hosts import (
    address_problem,
    ascii_host,
    is_host_name,
    is_server,
    unicode_host,
)


@pytest.mark.parametrize(
    ("given", "written"),
    [
        ("Example.DE.", "example.de"),
        (" mail.example.com ", "mail.example.com"),
        ("bücher.de", "xn--bcher-kva.de"),
        ("xn--bcher-kva.de", "xn--bcher-kva.de"),
        ("a..b", None),
        ("xn--zz.de", None),
        ("x" * 64 + ".de", None),
    ],
)
def test_ascii_host(given: str, written: str | None) -> None:
    assert ascii_host(given) == written


def test_unicode_host() -> None:
    assert unicode_host("xn--bcher-kva.de") == "bücher.de"
    assert unicode_host("example.de") == "example.de"
    assert unicode_host("xn--zz.de") == "xn--zz.de"


@pytest.mark.parametrize(
    ("host", "valid"),
    [
        ("example.de", True),
        ("mx00.t-online.de", True),
        ("xn--bcher-kva.xn--p1ai", True),
        ("localhost", False),
        ("10.0.0.1", False),
        ("example.de:993", False),
        ("-bad.de", False),
        ("bad-.de", False),
        ("a" * 250 + ".de", False),
    ],
)
def test_is_host_name(host: str, valid: bool) -> None:
    assert is_host_name(host) is valid


def test_a_name_of_one_label_is_a_name_in_the_dns() -> None:
    assert is_host_name("de", dotted=False)
    assert is_host_name("10.0.0.1", dotted=False)
    assert not is_host_name("x:8443", dotted=False)


@pytest.mark.parametrize(
    ("host", "valid"),
    [
        ("imap.example.org", True),
        ("bücher.example", True),
        ("localhost", True),
        ("10.0.0.5", True),
        ("::1", True),
        ("imap.example.org:993", False),
        ("[::1]", False),
        ("imap.example.org/x", False),
        ("imap\t.example.org", False),
        ("imap.example.org\r\n", False),
        ("imap.exa mple.org", False),
        ("imap\x00.example.org", False),
        ("imap..example.org", False),
        ("xn--zz.example", False),
        ("http://imap.example.org", False),
        ("", False),
    ],
)
def test_a_server_is_a_name_or_an_address(host: str, valid: bool) -> None:
    assert is_server(host) is valid


@pytest.mark.parametrize(
    ("email", "problem"),
    [
        ("me@example.org", None),
        ("me@bücher.example", None),
        ("o'brien+tag@example.org", None),
        ("nope", "address"),
        ("", "address"),
        ("@example.org", "address"),
        ("me@", "address"),
        ("m e@example.org", "address"),
        ("me\r\n@example.org", "address"),
        ("me @example.org", "address"),
        ("me\u0085@example.org", "address"),
        ("me\x00@example.org", "address"),
        ("me@" + "a" * 260 + ".org", "address"),
        ("me@example.org:8443", "domain"),
        ("me@[127.0.0.1]", "domain"),
        ("me@xn--zz.example", "domain"),
        ("me@example..org", "domain"),
    ],
)
def test_an_address_names_its_problem(email: str, problem: str | None) -> None:
    found = address_problem(email)
    assert found is None if problem is None else f"valid email {problem}" in found
