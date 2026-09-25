"""The SMTP module, and accounts that can send (CONCEPT 5, 6.1)."""

from __future__ import annotations

import smtplib
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.models import ProviderType
from benethos_mailbox_service.data.providers import CredentialReader, ProviderSettings
from benethos_mailbox_service.data.providers.imap import ImapProvider
from benethos_mailbox_service.data.providers.protocols.imap import ImapSession
from benethos_mailbox_service.data.providers.protocols.smtp import (
    SmtpLogin,
    SmtpServer,
    SmtpSession,
)
from benethos_mailbox_service.data.secrets import cipher, encode_recovery
from benethos_mailbox_service.errors import (
    BadRequestError,
    ProviderAuthError,
    ProviderError,
    ProviderUnavailableError,
)
from benethos_mailbox_service.main import build_services, create_app

from .imap_fake import FakeMailBox
from .smtp_fake import FakeSmtpServer

SERVER = SmtpServer("smtp.example.com", 465, "tls")
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


# --- PATCH /v1/accounts ---------------------------------------------------------------


@pytest.fixture
def world(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, FakeSmtpServer]]:
    monkeypatch.setenv("MAILBOX_SERVICE_MASTER_KEY", encode_recovery(cipher.new_key()))
    box, smtp = FakeMailBox(), FakeSmtpServer()

    def factory(
        kind: ProviderType, settings: ProviderSettings, credentials: CredentialReader
    ) -> ImapProvider:
        return ImapProvider(
            settings,
            credentials,
            session_factory=lambda s: ImapSession(s, client_factory=box),
            smtp_factory=lambda server: SmtpSession(server, connection_factory=smtp),
            sleep=lambda seconds: None,
        )

    settings = Settings(storage="memory", api_key=SecretStr("k"))
    services = build_services(settings, provider_factory=factory)
    services.vault.initialize()
    yield (
        TestClient(
            create_app(settings, services), headers={"Authorization": "Bearer k"}
        ),
        smtp,
    )


def new_account(client: TestClient) -> str:
    created = client.post(
        "/v1/accounts",
        json={
            "provider": "imap",
            "email": "me@example.com",
            "settings": IMAP_SETTINGS,
            "credentials": {"password": "secret"},
        },
    )
    assert created.status_code == 201
    return str(created.json()["id"])


def test_add_an_smtp_server_to_an_account(
    world: tuple[TestClient, FakeSmtpServer],
) -> None:
    client, smtp = world
    account_id = new_account(client)
    answer = client.patch(
        f"/v1/accounts/{account_id}",
        json={"settings": {"smtp_host": "smtp.example.com"}, "display_name": "Me"},
    )
    assert answer.status_code == 200
    assert answer.json()["display_name"] == "Me"
    # Tried before it was stored.
    assert ("login", "me@example.com") in smtp.calls


def test_a_change_that_does_not_log_in_is_not_stored(
    world: tuple[TestClient, FakeSmtpServer],
) -> None:
    client, smtp = world
    account_id = new_account(client)
    smtp.password = "other"
    answer = client.patch(
        f"/v1/accounts/{account_id}",
        json={"settings": {"smtp_host": "smtp.example.com"}},
    )
    assert answer.status_code == 502
    smtp.calls.clear()
    # Unchanged: a verify does not touch SMTP, since no server is stored.
    assert client.post(f"/v1/accounts/{account_id}/verify").status_code == 200
    assert smtp.calls == []


def test_settings_sent_as_stored_log_in_nowhere(
    world: tuple[TestClient, FakeSmtpServer],
) -> None:
    client, smtp = world
    account_id = new_account(client)
    url = f"/v1/accounts/{account_id}"
    client.patch(url, json={"settings": {"smtp_host": "smtp.example.com"}})
    smtp.calls.clear()
    same = client.patch(
        url,
        json={
            "display_name": "Renamed",
            "settings": {"smtp_host": "smtp.example.com", "smtp_port": None},
        },
    )
    assert same.status_code == 200 and same.json()["display_name"] == "Renamed"
    assert smtp.calls == []


def test_a_setting_is_removed_with_null(
    world: tuple[TestClient, FakeSmtpServer],
) -> None:
    client, smtp = world
    account_id = new_account(client)
    url = f"/v1/accounts/{account_id}"
    client.patch(url, json={"settings": {"smtp_host": "smtp.example.com"}})
    assert client.patch(url, json={"settings": {"smtp_host": None}}).status_code == 200
    smtp.calls.clear()
    assert client.post(f"{url}/verify").status_code == 200
    assert smtp.calls == []


def test_only_a_display_name_logs_in_nowhere(
    world: tuple[TestClient, FakeSmtpServer],
) -> None:
    client, smtp = world
    account_id = new_account(client)
    smtp.calls.clear()
    answer = client.patch(f"/v1/accounts/{account_id}", json={"display_name": "Me"})
    assert answer.status_code == 200
    assert smtp.calls == []
