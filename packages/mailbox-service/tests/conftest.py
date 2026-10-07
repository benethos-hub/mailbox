"""Fixtures shared by the suite. Everything is offline."""

from __future__ import annotations

import asyncio
import itertools
import logging
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service import config
from benethos_mailbox_service.assembly import Services, build_services, create_app
from benethos_mailbox_service.assembly import providers as assembly
from benethos_mailbox_service.common import redact
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
    ProviderSettings,
    Reads,
    build_provider,
)
from benethos_mailbox_service.data.providers.memory import MemoryProvider
from benethos_mailbox_service.data.secrets import (
    PasswordHasher,
    Scrypt,
    cipher,
    encode_recovery,
)
from benethos_mailbox_service.domain.accounts.service import AccountService
from benethos_mailbox_service.domain.auth.service import AuthService
from benethos_mailbox_service.domain.rights import ADMIN_SERVICE, permissions
from benethos_mailbox_service.domain.rights.access import Access

PUBLIC = "93.184.215.14"  # what every host resolves to, without DNS
METHODS = {"get", "post", "put", "patch", "delete"}  # of the OpenAPI document


async def resolve_to_public(host: str, port: int) -> list[str]:
    return [PUBLIC]


def admin_access(user_id: str, name: str) -> Access:
    """A caller with every right, for tests that call the domain."""
    return Access(user_id, name, [], service=ADMIN_SERVICE)


ADMIN = admin_access("usr_test_admin", "test admin")


def forget_secrets() -> None:
    """No secret is noted to be masked: the test reaches inside redact."""
    with redact._lock:
        redact._known.clear()


@pytest.fixture(autouse=True)
def no_secret_of_another_test() -> None:
    """Each test starts with no secret noted to be masked."""
    forget_secrets()


@pytest.fixture(autouse=True)
def logging_as_it_was() -> Iterator[None]:
    """``serve`` sets up the log. Afterwards it is as it was: a handler
    left behind would write to the stream of a test that has ended."""
    names = [
        "",
        "benethos_mailbox_service",
        "uvicorn",
        "uvicorn.error",
        "uvicorn.access",
    ]
    before = {
        name: (log.level, list(log.handlers), log.propagate)
        for name in names
        for log in [logging.getLogger(name)]
    }
    yield
    for name, (level, handlers, propagate) in before.items():
        log = logging.getLogger(name)
        log.setLevel(level)
        log.handlers[:] = handlers
        log.propagate = propagate


@pytest.fixture(autouse=True)
def no_configuration_from_this_machine(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """The suite must not read a developer's ``.env`` or environment, and must
    never write into the real data directory."""
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    # Nor the settings file in the repository, which load_settings reads,
    # nor the folders of the operating system.
    monkeypatch.setattr(config, "ENV_FILE", f"config/{config.APP}/no-such.env")
    system = tmp_path_factory.mktemp("system")
    monkeypatch.setattr(
        config, "system_folders", lambda: (system / "config", system / "data")
    )
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
    monkeypatch.setattr(assembly, "host_addresses", resolve_to_public)


@pytest.fixture
def settings() -> Settings:
    return Settings(storage="memory")


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
    ) -> Reads:
        if kind is ProviderType.MEMORY:
            return MemoryProvider(messages=messages)
        return build_provider(kind, provider_settings, credentials)

    return build_services(settings, provider_factory=factory, password_hasher=CHEAP)


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
    return TestClient(app, headers=admin_bearer(services))


# Names are unique: each limited user gets a number.
_LIMITED = itertools.count(1)
_BROWSER = itertools.count(1)

# Cheap to hash, so tests that sign in run fast. The service uses Scrypt().
CHEAP = PasswordHasher(Scrypt(log_n=4, r=1, p=1))
UI_PASSWORD = "a passphrase for the tests"


def browser_user(
    services: Services,
    *grants: Grant,
    roles: list[str] | None = None,
    service: list[str] | None = None,
    name: str | None = None,
) -> tuple[str, str]:
    """A user with these rights and a password it need not change: the
    name and the password to sign in to the UI with."""
    name = name or f"browser-{next(_BROWSER)}"
    user = services.users.create_user(
        ADMIN, name, roles or [], list(grants), service=service, ui_sign_in=True
    )
    asyncio.run(
        services.auth.passwords.set(user.id, name, UI_PASSWORD, must_change=False)
    )
    return name, UI_PASSWORD


def admin_bearer(services: Services) -> dict[str, str]:
    """The header of a token of a user with every right: the API's
    administrator in a test."""
    name = f"api-admin-{next(_LIMITED)}"
    user = services.users.create_user(ADMIN, name, [], [], service=[permissions.ADMIN])
    _, plain = services.auth.issue_token(user.id, "tests")
    return {"Authorization": f"Bearer {plain}"}


def browser_admin(services: Services) -> tuple[str, str]:
    """A user with every right, to sign in to the UI with."""
    return browser_user(services, service=[permissions.ADMIN], name="admin")


def bearer_for(
    services: Services,
    *grants: Grant,
    roles: list[str] | None = None,
    service: list[str] | None = None,
) -> dict[str, str]:
    """A user with these rights, and the header of a fresh token for it."""
    name = f"limited-{next(_LIMITED)}"
    user = services.users.create_user(
        ADMIN, name, roles or [], list(grants), service=service
    )
    _, plain = services.auth.issue_token(user.id, "test")
    return {"Authorization": f"Bearer {plain}"}


def create_account(accounts: AccountService, *args: Any, **kwargs: Any) -> Account:
    """``AccountService.create`` as the admin, for tests that are not async."""
    return asyncio.run(accounts.create(ADMIN, *args, **kwargs))


@pytest.fixture
def ui(app_client: TestClient, services: Services) -> TestClient:
    """A browser signed in to the configuration UI as a user with every
    right."""
    from .ui_helpers import sign_in

    sign_in(app_client, *browser_admin(services))
    return app_client
