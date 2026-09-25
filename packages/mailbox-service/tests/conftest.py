"""Fixtures shared by the suite. Everything is offline."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from benethos_mailbox_service import main
from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.models import (
    Account,
    Address,
    Grant,
    Message,
    ProviderType,
)
from benethos_mailbox_service.data.providers import (
    CredentialReader,
    MailProvider,
    ProviderSettings,
    build_provider,
)
from benethos_mailbox_service.data.providers.memory import MemoryProvider
from benethos_mailbox_service.data.secrets import cipher, encode_recovery
from benethos_mailbox_service.domain.access import Access
from benethos_mailbox_service.domain.accounts import AccountService
from benethos_mailbox_service.domain.auth import AuthService
from benethos_mailbox_service.main import Services, build_services, create_app

API_KEY = "test-key"
PUBLIC = "93.184.215.14"  # what every host resolves to, without DNS
METHODS = {"get", "post", "put", "patch", "delete"}  # of the OpenAPI document


async def resolve_to_public(host: str, port: int) -> list[str]:
    return [PUBLIC]


ADMIN = Access.admin("usr_test_admin", "test admin")


@pytest.fixture(autouse=True)
def no_configuration_from_this_machine(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """The suite must not read a developer's ``.env`` or environment, and must
    never write into the real data directory."""
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    for name in list(os.environ):
        if name.startswith("MAILBOX_SERVICE_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("MAILBOX_SERVICE_DATA_DIR", str(tmp_path_factory.mktemp("data")))
    # Tests that want SQLite ask for it.
    monkeypatch.setenv("MAILBOX_SERVICE_STORAGE", "memory")
    # Never the machine's real credential store.
    monkeypatch.setenv("MAILBOX_SERVICE_KEY_PROVIDER", "env")
    # No background worker. Tests that want one build it.
    monkeypatch.setenv("MAILBOX_SERVICE_SYNC_INTERVAL", "0")
    # No DNS: every host name in a test resolves to one public address, so
    # the host check of accounts and discovery passes without the network.
    # Tests of the check itself hand ``build_services`` a table.
    monkeypatch.setattr(main, "host_addresses", resolve_to_public)


@pytest.fixture
def settings() -> Settings:
    return Settings(api_key=SecretStr(API_KEY), storage="memory")


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
def services(settings: Settings, messages: list[Message]) -> Services:
    """The real services, with the memory adapter preloaded with ``messages``.

    Swapped in through the provider factory, the same seam a deployment uses
    to choose its adapters. Other provider types go to the real registry.
    """

    def factory(
        kind: ProviderType,
        provider_settings: ProviderSettings,
        credentials: CredentialReader,
    ) -> MailProvider:
        if kind is ProviderType.MEMORY:
            return MemoryProvider(messages=messages)
        return build_provider(kind, provider_settings, credentials)

    return build_services(settings, provider_factory=factory)


@pytest.fixture
def accounts(services: Services) -> AccountService:
    return services.accounts


@pytest.fixture
def auth(services: Services) -> AuthService:
    return services.auth


@pytest.fixture
def account_id(accounts: AccountService) -> str:
    return create_account(accounts, ProviderType.MEMORY, "me@example.com").id


@pytest.fixture
def master_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """A vault key in the environment, for tests that store credentials."""
    monkeypatch.setenv("MAILBOX_SERVICE_MASTER_KEY", encode_recovery(cipher.new_key()))


def memory_of(services: Services, account_id: str) -> MemoryProvider:
    """The memory adapter behind an account, to look at what it holds."""
    provider = services.adapters.get(account_id)
    assert isinstance(provider, MemoryProvider)
    return provider


@pytest.fixture
def app_client(settings: Settings, services: Services) -> TestClient:
    """A client without credentials, for tests that bring their own token."""
    return TestClient(create_app(settings, services))


@pytest.fixture
def client(settings: Settings, services: Services) -> TestClient:
    app = create_app(settings, services)
    return TestClient(app, headers={"Authorization": f"Bearer {API_KEY}"})


def bearer_for(
    services: Services, *grants: Grant, roles: list[str] | None = None
) -> dict[str, str]:
    """A user with these grants, and the header of a fresh token for it."""
    user = services.users.create_user(ADMIN, "limited", roles or [], list(grants))
    _, plain = services.auth.issue_token(user.id, "test")
    return {"Authorization": f"Bearer {plain}"}


def create_account(accounts: AccountService, *args: Any, **kwargs: Any) -> Account:
    """``AccountService.create`` as the admin, for tests that are not async."""
    return asyncio.run(accounts.create(ADMIN, *args, **kwargs))


@pytest.fixture
def ui(app_client: TestClient) -> TestClient:
    """A browser signed in to the configuration UI with the admin key."""
    from .ui_helpers import sign_in

    sign_in(app_client)
    return app_client
