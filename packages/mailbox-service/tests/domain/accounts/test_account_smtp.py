"""An SMTP server added to an IMAP account, changed and removed through
PATCH /v1/accounts: tried before it is stored, and logged in to only where
the settings name a new server (CONCEPT 5, 6.1)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service.assembly import build_services, create_app
from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.models import ProviderType
from benethos_mailbox_service.data.protocols.imap import ImapSession
from benethos_mailbox_service.data.protocols.smtp import SmtpSession
from benethos_mailbox_service.data.providers import (
    CredentialReader,
    ProviderSettings,
    Timing,
)
from benethos_mailbox_service.data.providers.imap import ImapProvider

from ...conftest import admin_bearer, set_master_key
from ...imap_fake import FakeMailBox
from ...smtp_fake import FakeSmtpServer

IMAP_SETTINGS = {"host": "imap.example.com", "username": "me@example.com"}


@pytest.fixture
def world(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, FakeSmtpServer]]:
    set_master_key(monkeypatch)
    box, smtp = FakeMailBox(), FakeSmtpServer()

    def factory(
        kind: ProviderType, settings: ProviderSettings, credentials: CredentialReader
    ) -> ImapProvider:
        return ImapProvider(
            settings,
            credentials,
            session_factory=lambda s: ImapSession(s, client_factory=box),
            smtp_factory=lambda server: SmtpSession(server, connection_factory=smtp),
            timing=Timing(sleep=lambda seconds: None),
        )

    settings = Settings(storage="memory")
    services = build_services(settings, provider_factory=factory)
    services.vault.initialize()
    yield (
        TestClient(create_app(settings, services), headers=admin_bearer(services)),
        smtp,
    )


# A server the account did not name before needs the password again.
PASSWORD = {"password": "secret"}


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
        json={
            "settings": {"smtp_host": "smtp.example.com"},
            "credentials": PASSWORD,
            "display_name": "Me",
        },
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
        json={"settings": {"smtp_host": "smtp.example.com"}, "credentials": PASSWORD},
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
    added = {"settings": {"smtp_host": "smtp.example.com"}, "credentials": PASSWORD}
    assert client.patch(url, json=added).status_code == 200
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
    added = {"settings": {"smtp_host": "smtp.example.com"}, "credentials": PASSWORD}
    assert client.patch(url, json=added).status_code == 200
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


def test_a_new_server_needs_the_password_again(
    world: tuple[TestClient, FakeSmtpServer],
) -> None:
    client, smtp = world
    url = f"/v1/accounts/{new_account(client)}"
    smtp.calls.clear()
    alone = client.patch(url, json={"settings": {"smtp_host": "smtp.example.com"}})
    assert alone.status_code == 400
    assert "smtp_host" in alone.json()["error"]["message"]
    # The stored password went nowhere.
    assert smtp.calls == []
