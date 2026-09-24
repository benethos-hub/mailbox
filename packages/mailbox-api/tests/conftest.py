"""Fixtures shared by the suite. Everything is offline."""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from benethos_mailbox_api.config import Settings
from benethos_mailbox_api.data.models import Address, Message, ProviderType
from benethos_mailbox_api.data.providers import (
    MailProvider,
    ProviderSettings,
    build_provider,
)
from benethos_mailbox_api.data.providers.memory import MemoryProvider
from benethos_mailbox_api.data.storage import InMemoryAccountRepository
from benethos_mailbox_api.domain.accounts import AccountService
from benethos_mailbox_api.main import create_app

API_KEY = "test-key"


@pytest.fixture(autouse=True)
def no_configuration_from_this_machine(monkeypatch: pytest.MonkeyPatch) -> None:
    """The suite must not read a developer's ``.env`` or environment."""
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    for name in list(os.environ):
        if name.startswith("MAILBOX_API_"):
            monkeypatch.delenv(name)


@pytest.fixture
def settings() -> Settings:
    return Settings(api_key=SecretStr(API_KEY))


@pytest.fixture
def messages() -> list[Message]:
    return [
        Message(
            id=f"m{i}",
            folder_ids=["inbox"],
            subject=f"Invoice {i}" if i % 2 else f"Hello {i}",
            sender=Address(email="alice@example.com", name="Alice"),
            to=[Address(email="me@example.com")],
            date=datetime(2026, 9, i + 1, tzinfo=UTC),
            unread=i < 2,
            text_body=f"body {i}",
        )
        for i in range(5)
    ]


@pytest.fixture
def accounts(messages: list[Message]) -> AccountService:
    """The real service, with the memory adapter preloaded with ``messages``.

    Swapped in through the provider factory, the same seam a deployment uses
    to choose its adapters. Other provider types go to the real registry.
    """

    def factory(kind: ProviderType, settings: ProviderSettings) -> MailProvider:
        if kind is ProviderType.MEMORY:
            return MemoryProvider(messages=messages)
        return build_provider(kind, settings)

    return AccountService(InMemoryAccountRepository(), provider_factory=factory)


@pytest.fixture
def account_id(accounts: AccountService) -> str:
    return accounts.create(ProviderType.MEMORY, "me@example.com").id


@pytest.fixture
def client(settings: Settings, accounts: AccountService) -> TestClient:
    app = create_app(settings, accounts)
    return TestClient(app, headers={"Authorization": f"Bearer {API_KEY}"})
