"""The receiving server's statement about the sender, read from its
Authentication-Results entry: the table of docs/CONCEPT.md row by row,
and the forgeries it must not believe."""

from __future__ import annotations

import pytest

from benethos_mailbox_service.data.mail.authentication import (
    MAX_ENTRY,
    Trust,
    host,
    sender_check,
)
from benethos_mailbox_service.data.models import SenderCheck

OWN = Trust(("mx.example.org",))
SENDER = "billing@example.com"


def check(
    *entries: str, sender: str | None = SENDER, trust: Trust | None = OWN
) -> SenderCheck:
    return sender_check(list(entries), sender, trust)


def unknown(reason: str) -> SenderCheck:
    return SenderCheck.model_validate({"result": "unknown", "reason": reason})


PASSED = SenderCheck(
    result="pass", domain="example.com", matches_from=True, method="dmarc"
)


# --- the three marks of the request ---------------------------------------------


def test_mark_1_dmarc_pass_of_the_own_server_is_pass() -> None:
    entry = "mx.example.org; dmarc=pass header.from=example.com"
    assert check(entry) == PASSED


def test_mark_2_a_forged_second_entry_of_the_own_server_spoils_it() -> None:
    real = "mx.example.org; dmarc=pass header.from=example.com"
    forged = "mx.example.org; dmarc=pass header.from=example.com"
    assert check(forged, real) == unknown("several_entries")


def test_mark_3_an_account_that_cannot_tell_is_unknown() -> None:
    entry = "mx.example.org; dmarc=pass header.from=example.com"
    assert check(entry, trust=None) == unknown("account")


# --- the table, row by row -----------------------------------------------------


def test_no_entry_of_the_own_server() -> None:
    assert check() == unknown("no_entry")
    assert check("mx.example.net; dmarc=pass header.from=example.com") == unknown(
        "no_entry"
    )


def test_an_unreadable_entry() -> None:
    assert check("mx.example.org; dmarc=pass header.from=(unended") == unknown(
        "unreadable"
    )
    assert check('mx.example.org; dkim=pass reason="unended') == unknown("unreadable")
    assert check("mx.example.org; dmarc=pass header.from") == unknown("unreadable")


@pytest.mark.parametrize("sender", [None, "nobody", "a@exa mple.com", "a@"])
def test_a_sender_without_one_readable_domain(sender: str | None) -> None:
    entry = "mx.example.org; dmarc=pass header.from=example.com"
    assert check(entry, sender=sender) == unknown("unreadable")


def test_dmarc_pass_for_another_domain_differs() -> None:
    entry = "mx.example.org; dmarc=pass header.from=example.net"
    assert check(entry) == SenderCheck(
        result="unknown",
        domain="example.net",
        matches_from=False,
        method="dmarc",
        reason="from_differs",
    )
    assert check("mx.example.org; dmarc=pass") == SenderCheck(
        result="unknown", matches_from=False, method="dmarc", reason="from_differs"
    )


def test_dmarc_fail() -> None:
    entry = "mx.example.org; dmarc=fail header.from=example.com"
    assert check(entry) == SenderCheck(
        result="fail", domain="example.com", matches_from=True, method="dmarc"
    )
    other = "mx.example.org; dmarc=fail header.from=example.net"
    assert check(other).matches_from is False
    assert check("mx.example.org; dmarc=fail") == SenderCheck(
        result="fail", method="dmarc"
    )


def test_dkim_of_the_sender_without_dmarc() -> None:
    entry = "mx.example.org; dkim=pass header.d=example.com; dmarc=none"
    assert check(entry) == SenderCheck(
        result="pass", domain="example.com", matches_from=True, method="dkim"
    )


def test_dkim_by_the_identity_as_gmail_writes_it() -> None:
    entry = (
        "mx.example.org; dkim=pass header.i=@example.com header.s=s1 header.b=AbC+/9"
    )
    assert check(entry).method == "dkim"
    assert check(entry).result == "pass"


def test_spf_of_the_sender_without_dmarc() -> None:
    for mailfrom in ("bounce@example.com", "example.com"):
        entry = f"mx.example.org; spf=pass smtp.mailfrom={mailfrom}"
        assert check(entry) == SenderCheck(
            result="pass", domain="example.com", matches_from=True, method="spf"
        )


def test_dkim_before_spf() -> None:
    entry = (
        "mx.example.org; spf=pass smtp.mailfrom=example.com; "
        "dkim=pass header.d=example.com"
    )
    assert check(entry).method == "dkim"


def test_another_domain_only() -> None:
    entry = "mx.example.org; dkim=pass header.d=example.net; spf=fail"
    assert check(entry) == SenderCheck(
        result="unknown",
        domain="example.net",
        matches_from=False,
        method="dkim",
        reason="other_domain",
    )


def test_two_dkim_results_one_of_them_the_sender() -> None:
    entry = (
        "mx.example.org; dkim=pass header.d=example.net; dkim=pass header.d=example.com"
    )
    assert check(entry).result == "pass"


@pytest.mark.parametrize("method", ["dmarc", "dkim", "spf"])
def test_an_error_of_a_check(method: str) -> None:
    assert check(f"mx.example.org; {method}=temperror") == unknown("error")
    assert check(f"mx.example.org; {method}=permerror") == unknown("error")


def test_nothing_confirms_the_sender() -> None:
    assert check("mx.example.org; spf=fail smtp.mailfrom=example.com") == unknown(
        "no_proof"
    )
    assert check("mx.example.org; none") == unknown("no_proof")


@pytest.mark.parametrize("value", ["none", "skipped", "bestguesspass"])
def test_these_dmarc_values_are_no_dmarc_result(value: str) -> None:
    entry = (
        f"mx.example.org; dmarc={value} header.from=example.com; "
        "spf=pass smtp.mailfrom=example.com"
    )
    assert check(entry).method == "spf"


def test_compauth_beside_dmarc_fail_stays_fail() -> None:
    entry = (
        "mx.example.org 1; dmarc=fail action=quarantine header.from=example.com; "
        "compauth=pass reason=130"
    )
    assert check(entry).result == "fail"


# --- forgeries -------------------------------------------------------------------


def test_an_entry_of_another_server_is_passed_over() -> None:
    real = "mx.example.org; dmarc=pass header.from=example.com"
    foreign = "mx.example.net; dmarc=pass header.from=example.com"
    assert check(foreign, real) == PASSED
    assert check(foreign) == unknown("no_entry")


@pytest.mark.parametrize(
    ("trust", "authserv_id"),
    [
        (("mx.example.org",), "mx.example.org.example.net"),
        (("mx.example.org",), "xmx.example.org"),
        ((".example.org",), "example.org"),
        ((".example.org",), "mx.example.org.example.net"),
    ],
)
def test_a_name_only_alike_does_not_count(
    trust: tuple[str, ...], authserv_id: str
) -> None:
    entry = f"{authserv_id}; dmarc=pass header.from=example.com"
    assert check(entry, trust=Trust(trust)) == unknown("no_entry")


def test_a_leading_dot_trusts_every_host_below() -> None:
    entry = "mx2.Example.ORG; dmarc=pass header.from=example.com"
    assert check(entry, trust=Trust((".example.org",))) == PASSED


def test_a_comment_is_no_statement() -> None:
    entry = (
        "mx.example.org; spf=fail (dmarc=pass header.from=example.com) "
        "smtp.mailfrom=example.net"
    )
    assert check(entry) == unknown("no_proof")


def test_a_quoted_string_is_no_statement() -> None:
    entry = 'mx.example.org; dkim=fail reason="x; dmarc=pass header.from=example.com"'
    assert check(entry) == unknown("no_proof")


@pytest.mark.parametrize(
    "domain",
    [
        "exa mple.com",
        "example.com\r\n evil",
        "exämple.com",
        "a" * 300,
        "example.com;x=1",
    ],
)
def test_a_domain_that_is_no_host_name_is_unreadable(domain: str) -> None:
    entry = f'mx.example.org; dmarc=pass header.from="{domain}"'
    found = check(entry)
    assert found == unknown("unreadable")
    assert domain not in found.model_dump_json()


def test_an_entry_over_the_limit_is_unreadable() -> None:
    entry = "mx.example.org; dmarc=pass header.from=example.com " + "x=y " * MAX_ENTRY
    assert check(entry) == unknown("unreadable")


# --- the form of the header -----------------------------------------------------


def test_folded_lines_case_and_a_version() -> None:
    entry = (
        "MX.Example.Org 1;\r\n\tSPF=pass smtp.mailfrom=example.com;\r\n"
        " DMARC=Pass (p=NONE) header.from=Example.COM"
    )
    assert check(entry) == PASSED


def test_space_around_the_equals_sign_and_a_method_version() -> None:
    entry = "mx.example.org; dkim/1 = pass header.d = example.com"
    assert check(entry).method == "dkim"


def test_methods_unknown_to_the_reader_are_passed_over() -> None:
    entry = (
        "mx.example.org; iprev=pass policy.iprev=192.0.2.1; arc=pass (i=1); "
        "dara=neutral header.i=@example.com; dmarc=pass header.from=example.com"
    )
    assert check(entry) == PASSED


def test_a_trailing_semicolon() -> None:
    assert check("mx.example.org; dmarc=pass header.from=example.com;") == PASSED


def test_an_international_sender_compares_in_ascii() -> None:
    entry = "mx.example.org; dmarc=pass header.from=xn--bcher-kva.example"
    found = check(entry, sender="a@bücher.example")
    assert found.result == "pass"
    assert found.domain == "xn--bcher-kva.example"


def test_host() -> None:
    assert host("Example.COM.") == "example.com"
    assert host("ex_ample.com") is None
    assert host("") is None
