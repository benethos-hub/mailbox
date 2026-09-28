"""Host names in one form."""

from __future__ import annotations

import pytest

from benethos_mailbox_service.common.hosts import ascii_host, is_host_name, unicode_host


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
