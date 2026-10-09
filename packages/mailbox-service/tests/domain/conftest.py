"""Fixtures shared by the tests of the domain: an IMAP account and webhooks."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import SecretStr

from benethos_mailbox_service.assembly import Services, build_services
from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.models import ProviderType
from benethos_mailbox_service.data.protocols.imap import ImapSession
from benethos_mailbox_service.data.providers import (
    CredentialReader,
    ProviderSettings,
    Reads,
)
from benethos_mailbox_service.data.providers.imap import ImapProvider
from benethos_mailbox_service.data.providers.memory import MemoryProvider
from benethos_mailbox_service.data.secrets import cipher, encode_recovery

from ..conftest import create_account
from ..imap_fake import FakeFolder, FakeMailBox, make_message

# --- an IMAP account through the real services -----------------------------------


@pytest.fixture
def imap_server() -> FakeMailBox:
    box = FakeMailBox()
    box.folders = {"INBOX": FakeFolder(uidvalidity=7), "Archive": FakeFolder()}
    for uid in range(1, 5):
        box.add(
            "INBOX",
            uid,
            make_message(f"Mail {uid}", date=datetime(2026, 9, uid, tzinfo=UTC)),
        )
    return box


@pytest.fixture
def imap_services(
    imap_server: FakeMailBox, monkeypatch: pytest.MonkeyPatch
) -> Services:
    monkeypatch.setenv("MAILBOX_SERVICE_MASTER_KEY", encode_recovery(cipher.new_key()))

    def factory(
        kind: ProviderType, settings: ProviderSettings, credentials: CredentialReader
    ) -> Reads:
        if kind is ProviderType.MEMORY:
            return MemoryProvider()
        return ImapProvider(
            settings,
            credentials,
            session_factory=lambda s: ImapSession(s, client_factory=imap_server),
            sleep=lambda seconds: None,
        )

    imap_services = build_services(Settings(storage="memory"), provider_factory=factory)
    imap_services.vault.initialize()
    return imap_services


@pytest.fixture
def imap_account_id(imap_services: Services) -> str:
    return create_account(
        imap_services.accounts,
        ProviderType.IMAP,
        "me@example.com",
        settings={"host": "imap.example.com", "username": "me@example.com"},
        credentials={"password": SecretStr("secret")},
    ).id


# --- webhooks -----------------------------------------------------------------------


class Receiver:
    """Stands in for the WebhookPoster: records each post, answers a status."""

    def __init__(self) -> None:
        self.posts: list[tuple[str, bytes, dict[str, str]]] = []
        self.status = 204
        self.failure: Exception | None = None

    async def post(self, url: str, body: bytes, headers: dict[str, str]) -> int:
        self.posts.append((url, body, dict(headers)))
        if self.failure is not None:
            raise self.failure
        return self.status

    def events(self, n: int = -1) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = json.loads(self.posts[n][1])["events"]
        return events


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def receiver(services: Services, monkeypatch: pytest.MonkeyPatch) -> Receiver:
    services.vault.initialize()
    fake = Receiver()
    monkeypatch.setattr(services.deliveries, "_poster", fake)
    return fake


@pytest.fixture
def delivery_clock(services: Services, monkeypatch: pytest.MonkeyPatch) -> Clock:
    """The clock of the webhook deliveries, which moves when a test says."""
    fixed = Clock()
    monkeypatch.setattr(services.deliveries, "_clock", fixed)
    return fixed
