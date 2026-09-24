"""Connected accounts and the live adapter behind each."""

from __future__ import annotations

import builtins
import uuid
from collections.abc import Mapping

from pydantic import SecretStr

from ..data.models import Account, ProviderType
from ..data.providers import (
    CredentialReader,
    MailProvider,
    ProviderFactory,
    ProviderSettings,
    build_provider,
)
from ..data.secrets import CredentialVault
from ..data.storage import AccountRepository
from .access import Access


class AccountService:
    """Owns the one adapter per account. Records live in the repository,
    credentials in the vault."""

    def __init__(
        self,
        repository: AccountRepository,
        vault: CredentialVault,
        provider_factory: ProviderFactory = build_provider,
    ) -> None:
        self._repository = repository
        self._vault = vault
        self._provider_factory = provider_factory
        self._providers: dict[str, MailProvider] = {}

    def list(self, access: Access) -> builtins.list[Account]:
        return [
            self._with_credentials(account)
            for account in self._repository.list()
            if access.allows("list_accounts", account.id)
        ]

    def get(self, access: Access, account_id: str) -> Account:
        access.require("get_account", account_id)
        return self._with_credentials(self._repository.get(account_id))

    def create(
        self,
        access: Access,
        provider: ProviderType,
        email: str,
        display_name: str | None = None,
        settings: ProviderSettings | None = None,
        credentials: Mapping[str, SecretStr] | None = None,
    ) -> Account:
        access.require("create_account")
        account = Account(
            id=f"acc_{uuid.uuid4().hex[:12]}",
            provider=provider,
            email=email,
            display_name=display_name,
        )
        # The adapter first: an unsupported provider leaves no record behind.
        adapter = self._provider_factory(
            provider, settings or {}, self._reader(account.id)
        )
        self._repository.add(account, dict(settings or {}))
        try:
            for field, value in (credentials or {}).items():
                self._vault.store(account.id, field, value)
        except BaseException:
            self._vault.delete(account.id)
            self._repository.delete(account.id)
            raise
        self._providers[account.id] = adapter
        return self._with_credentials(account)

    async def delete(self, access: Access, account_id: str) -> None:
        access.require("delete_account", account_id)
        self._vault.delete(account_id)
        self._repository.delete(account_id)
        adapter = self._providers.pop(account_id, None)
        if adapter is not None:
            await adapter.close()

    def all_ids(self) -> builtins.list[str]:
        """Every account id. Internal: callers filter by rights themselves."""
        return [account.id for account in self._repository.list()]

    def provider(self, account_id: str) -> MailProvider:
        """The adapter of an account, built on first use after a restart.
        Internal: callers check rights first."""
        account = self._repository.get(account_id)
        adapter = self._providers.get(account_id)
        if adapter is None:
            adapter = self._provider_factory(
                account.provider,
                self._repository.settings(account_id),
                self._reader(account_id),
            )
            self._providers[account_id] = adapter
        return adapter

    def _reader(self, account_id: str) -> CredentialReader:
        return lambda field: self._vault.read(account_id, field)

    def _with_credentials(self, account: Account) -> Account:
        return account.model_copy(update={"credentials": self._vault.info(account.id)})
