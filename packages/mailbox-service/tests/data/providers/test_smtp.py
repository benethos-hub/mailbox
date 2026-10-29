"""The SMTP module, and accounts that can send (CONCEPT 5, 6.1)."""

from __future__ import annotations

import smtplib

import pytest
from pydantic import SecretStr

from benethos_mailbox_service.data.protocols.imap import ImapSession
from benethos_mailbox_service.data.protocols.smtp import (
    Server,
    SmtpLogin,
    SmtpSession,
)
from benethos_mailbox_service.data.providers.imap import ImapProvider
from benethos_mailbox_service.errors import (
    BadRequestError,
    ProviderAuthError,
    ProviderError,
    ProviderUnavailableError,
)

from ...imap_fake import FakeMailBox
from ...smtp_fake import FakeSmtpServer

SERVER = Server("smtp.example.com", 465, "tls")
LOGIN = SmtpLogin("me@example.com", "secret")


def session(fake: FakeSmtpServer) -> SmtpSession:
    return SmtpSession(SERVER, connection_factory=fake)


# --- the SMTP module ---------------------------------------------------------------


def test_verify_logs_in_and_out() -> None:
    fake = FakeSmtpServer()
    session(fake).verify(LOGIN)
    assert fake.calls == [
        ("connect", "smtp.example.com", 465, "tls"),
        ("login", "me@example.com"),
        ("quit",),
    ]


def test_a_rejected_login() -> None:
    fake = FakeSmtpServer(password="other")
    with pytest.raises(ProviderAuthError):
        session(fake).verify(LOGIN)
    assert fake.calls[-1] == ("quit",)


def test_a_login_refused_for_now_is_no_rejection() -> None:
    fake = FakeSmtpServer(
        login_refusal=(454, b"4.7.0 Temporary authentication failure")
    )
    with pytest.raises(ProviderUnavailableError, match="for now"):
        session(fake).verify(LOGIN)


def test_a_password_beyond_ascii_is_refused_without_naming_it() -> None:
    fake = FakeSmtpServer(password="pässwort")
    with pytest.raises(BadRequestError, match="beyond ASCII") as refused:
        session(fake).verify(SmtpLogin("me@example.com", "pässwort"))
    assert "ä" not in refused.value.message
    assert ("login", "me@example.com") not in fake.calls


def test_a_refused_xoauth2_token_is_a_rejected_login() -> None:
    fake = FakeSmtpServer(password="fresh token")
    with pytest.raises(ProviderAuthError):
        session(fake).verify(SmtpLogin("me@example.com", "stale", "xoauth2"))


def test_xoauth2() -> None:
    fake = FakeSmtpServer(password="token")
    session(fake).verify(SmtpLogin("me@example.com", "token", "xoauth2"))
    assert ("auth", "XOAUTH2") in fake.calls


def test_send_reports_refused_recipients() -> None:
    fake = FakeSmtpServer(refuse={"nobody@example.com"})
    refused = session(fake).send(
        LOGIN, "me@example.com", ["you@example.com", "nobody@example.com"], b"raw"
    )
    assert refused == ["nobody@example.com"]
    assert fake.sent[0].recipients == ["you@example.com"]


def test_domains_go_in_punycode_and_a_unicode_local_part_needs_smtputf8() -> None:
    fake = FakeSmtpServer()
    refused = session(fake).send(
        LOGIN, "me@bücher.example", ["du@bücher.example"], b"x"
    )
    assert refused == []
    assert (fake.sent[0].sender, fake.sent[0].recipients, fake.sent[0].options) == (
        "me@xn--bcher-kva.example",
        ["du@xn--bcher-kva.example"],
        [],
    )
    with pytest.raises(BadRequestError, match="SMTPUTF8"):
        session(fake).send(LOGIN, "me@example.com", ["jürgen@example.com"], b"x")
    fake.extensions.add("smtputf8")
    session(fake).send(LOGIN, "me@example.com", ["jürgen@example.com"], b"x")
    assert fake.sent[-1].options == ["SMTPUTF8"]


def test_send_with_every_recipient_refused() -> None:
    fake = FakeSmtpServer(refuse={"nobody@example.com"})
    with pytest.raises(BadRequestError, match="refused every recipient"):
        session(fake).send(LOGIN, "me@example.com", ["nobody@example.com"], b"raw")


@pytest.mark.parametrize(
    ("failure", "error"),
    [
        (OSError("refused"), ProviderUnavailableError),
        (TimeoutError(), ProviderUnavailableError),
        (smtplib.SMTPServerDisconnected("gone"), ProviderUnavailableError),
        (smtplib.SMTPConnectError(421, b"busy"), ProviderError),
    ],
)
def test_connection_failures(failure: Exception, error: type[Exception]) -> None:
    with pytest.raises(error):
        session(FakeSmtpServer(failure=failure)).verify(LOGIN)


# --- accounts with an SMTP server ----------------------------------------------------


IMAP_SETTINGS = {"host": "imap.example.com", "username": "me@example.com"}


def imap(settings: dict[str, object], smtp: FakeSmtpServer) -> ImapProvider:
    return ImapProvider(
        settings,
        lambda field: SecretStr("secret"),
        session_factory=lambda s: ImapSession(s, client_factory=FakeMailBox()),
        smtp_factory=lambda server: SmtpSession(server, connection_factory=smtp),
    )


def test_smtp_security_must_encrypt() -> None:
    with pytest.raises(BadRequestError, match="smtp_security"):
        imap(
            {**IMAP_SETTINGS, "smtp_host": "smtp.x", "smtp_security": "none"},
            FakeSmtpServer(),
        )


async def test_verify_checks_smtp_too() -> None:
    smtp = FakeSmtpServer(password="other")
    provider = imap({**IMAP_SETTINGS, "smtp_host": "smtp.example.com"}, smtp)
    with pytest.raises(ProviderAuthError):
        await provider.verify()
    assert ("connect", "smtp.example.com", 465, "tls") in smtp.calls


async def test_starttls_on_587_and_an_own_login() -> None:
    smtp = FakeSmtpServer()
    provider = imap(
        {
            **IMAP_SETTINGS,
            "smtp_host": "smtp.example.com",
            "smtp_security": "starttls",
            "smtp_username": "sender",
        },
        smtp,
    )
    await provider.verify()
    assert ("connect", "smtp.example.com", 587, "starttls") in smtp.calls
    assert ("login", "sender") in smtp.calls
