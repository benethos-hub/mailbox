"""Verify, then store: an IMAP account through the API, against a fake server."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.models import ProviderType
from benethos_mailbox_service.data.providers import CredentialReader, ProviderSettings
from benethos_mailbox_service.data.providers.imap import ImapProvider
from benethos_mailbox_service.data.providers.protocols.imap import ImapSession
from benethos_mailbox_service.data.secrets import cipher, encode_recovery
from benethos_mailbox_service.main import Services, build_services, create_app

from .imap_fake import FakeMailBox, make_message

NEW_ACCOUNT = {
    "provider": "imap",
    "email": "me@example.com",
    "settings": {"host": "imap.example.com", "username": "me@example.com"},
    "credentials": {"password": "secret"},
}


@pytest.fixture
def server() -> FakeMailBox:
    box = FakeMailBox(password="secret")
    box.add("INBOX", 1, make_message("Hello"))
    return box


@pytest.fixture
def world(
    server: FakeMailBox, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[Services, TestClient]]:
    monkeypatch.setenv("MAILBOX_SERVICE_MASTER_KEY", encode_recovery(cipher.new_key()))

    def factory(
        kind: ProviderType, settings: ProviderSettings, credentials: CredentialReader
    ) -> ImapProvider:
        return ImapProvider(
            settings,
            credentials,
            session_factory=lambda s: ImapSession(s, client_factory=server),
            sleep=lambda seconds: None,
        )

    settings = Settings(storage="memory", api_key=SecretStr("k"))
    services = build_services(settings, provider_factory=factory)
    services.vault.initialize()
    yield (
        services,
        TestClient(
            create_app(settings, services), headers={"Authorization": "Bearer k"}
        ),
    )


def test_a_working_credential_is_stored(world, server: FakeMailBox) -> None:  # type: ignore[no-untyped-def]
    services, client = world
    response = client.post("/v1/accounts", json=NEW_ACCOUNT)
    assert response.status_code == 201
    account = response.json()
    assert [c["field"] for c in account["credentials"]] == ["password"]
    assert "secret" not in response.text
    # The probe logged in and out again. The stored account reads from the vault.
    assert ("logout",) in server.calls
    folders = client.get(f"/v1/accounts/{account['id']}/folders")
    assert folders.status_code == 200
    assert server.logins == 2


def test_a_wrong_credential_stores_nothing(world) -> None:  # type: ignore[no-untyped-def]
    services, client = world
    wrong = {**NEW_ACCOUNT, "credentials": {"password": "nope"}}
    response = client.post("/v1/accounts", json=wrong)
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "provider_auth_failed"
    assert client.get("/v1/accounts").json() == []


def test_a_missing_credential_is_a_bad_request(world) -> None:  # type: ignore[no-untyped-def]
    _, client = world
    missing = {**NEW_ACCOUNT, "credentials": {}}
    response = client.post("/v1/accounts", json=missing)
    assert response.status_code == 400
    assert "password" in response.json()["error"]["message"]
    assert client.get("/v1/accounts").json() == []


def test_bad_settings_store_nothing(world) -> None:  # type: ignore[no-untyped-def]
    _, client = world
    plain = {**NEW_ACCOUNT, "settings": {**NEW_ACCOUNT["settings"], "security": "none"}}
    assert client.post("/v1/accounts", json=plain).status_code == 400
    assert client.get("/v1/accounts").json() == []


def test_verify_after_the_password_changed(world, server: FakeMailBox) -> None:  # type: ignore[no-untyped-def]
    services, client = world
    account_id = client.post("/v1/accounts", json=NEW_ACCOUNT).json()["id"]

    server.password = "changed-at-the-provider"
    assert client.get(f"/v1/accounts/{account_id}/folders").status_code == 502
    assert client.get(f"/v1/accounts/{account_id}").json()["status"] == "needs_reauth"

    # Still wrong: verify says so and the account stays as it is.
    response = client.post(f"/v1/accounts/{account_id}/verify")
    assert response.status_code == 502
    assert client.get(f"/v1/accounts/{account_id}").json()["status"] == "needs_reauth"

    # Put right at the provider: verify clears the block.
    server.password = "secret"
    verified = client.post(f"/v1/accounts/{account_id}/verify")
    assert verified.status_code == 200
    assert verified.json()["status"] == "connected"
    assert client.get(f"/v1/accounts/{account_id}/folders").status_code == 200


def test_verify_needs_accounts_manage(world) -> None:  # type: ignore[no-untyped-def]
    services, client = world
    account_id = client.post("/v1/accounts", json=NEW_ACCOUNT).json()["id"]
    user = client.post(
        "/v1/users",
        json={"name": "r", "grants": [{"accounts": ["*"], "allow": ["mail.read"]}]},
    ).json()
    token = client.post(f"/v1/users/{user['id']}/tokens", json={"name": "t"}).json()
    response = client.post(
        f"/v1/accounts/{account_id}/verify",
        headers={"Authorization": f"Bearer {token['token']}"},
    )
    assert response.status_code == 403
