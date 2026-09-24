"""Connected accounts and the live adapter behind each."""

from __future__ import annotations

import builtins
import uuid
from collections.abc import Awaitable, Mapping
from typing import TypeVar

from pydantic import SecretStr

from ..data.models import Account, AccountStatus, ProviderType
from ..data.providers import (
    CredentialReader,
    MailProvider,
    ProviderFactory,
    ProviderSettings,
    build_provider,
)
from ..data.secrets import CredentialVault
from ..data.storage import AccountRepository, MessageIndexRepository
from ..errors import BadRequestError, ProviderAuthError, ProviderUnavailableError
from .access import Access

T = TypeVar("T")


class AccountService:
    """Owns the one adapter per account. Records live in the repository,
    credentials in the vault."""

    def __init__(
        self,
        repository: AccountRepository,
        vault: CredentialVault,
        provider_factory: ProviderFactory = build_provider,
        index: MessageIndexRepository | None = None,
    ) -> None:
        self._repository = repository
        self._vault = vault
        self._provider_factory = provider_factory
        self._index = index
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

    async def create(
        self,
        access: Access,
        provider: ProviderType,
        email: str,
        display_name: str | None = None,
        settings: ProviderSettings | None = None,
        credentials: Mapping[str, SecretStr] | None = None,
    ) -> Account:
        """Verify, then store: nothing is kept unless the provider accepts the
        credential."""
        access.require("create_account")
        secrets = dict(credentials or {})
        if secrets:
            self._vault.require_ready()
        account = Account(
            id=f"acc_{uuid.uuid4().hex[:12]}",
            provider=provider,
            email=email,
            display_name=display_name,
        )
        # A throwaway adapter that reads the credential from the request. An
        # unsupported provider or bad settings fail here, before anything is
        # stored.
        probe = self._provider_factory(
            provider, settings or {}, lambda field: _pending(secrets, field)
        )
        try:
            await probe.verify()
        finally:
            await probe.close()

        self._repository.add(account, dict(settings or {}))
        try:
            for field, value in secrets.items():
                self._vault.store(account.id, field, value)
        except BaseException:
            self._vault.delete(account.id)
            self._repository.delete(account.id)
            raise
        return self._with_credentials(account)

    async def update(
        self,
        access: Access,
        account_id: str,
        *,
        display_name: str | None,
        rename: bool,
        settings: Mapping[str, str | int | bool | None] | None = None,
        credentials: Mapping[str, SecretStr] | None = None,
    ) -> Account:
        """Change the display name, settings (``None`` removes one) or
        credentials. A change of settings or credentials logs in first, as on
        create: nothing is stored unless the provider accepts it."""
        access.require("update_account", account_id)
        account = self._repository.get(account_id)
        merged: dict[str, str | int | bool] = dict(
            self._repository.settings(account_id)
        )
        for key, value in (settings or {}).items():
            if value is None:
                merged.pop(key, None)
            else:
                merged[key] = value
        secrets = dict(credentials or {})
        if secrets:
            self._vault.require_ready()
        if settings or secrets:

            def read(field: str) -> SecretStr:
                if field in secrets:
                    return secrets[field]
                return self._vault.read(account_id, field)

            probe = self._provider_factory(account.provider, merged, read)
            try:
                await probe.verify()
            finally:
                await probe.close()
        if rename:
            account = account.model_copy(update={"display_name": display_name})
        self._repository.update(account, merged)
        for field, secret in secrets.items():
            self._vault.store(account_id, field, secret)
        if settings or secrets:
            # The live adapter still has the old settings: the next use
            # builds a new one.
            adapter = self._providers.pop(account_id, None)
            if adapter is not None:
                await adapter.close()
            self._set_status(account_id, AccountStatus.CONNECTED)
        return self._with_credentials(self._repository.get(account_id))

    async def verify(self, access: Access, account_id: str) -> Account:
        """Log in afresh, e.g. after the credential was changed at the
        provider. Clears a rejected login and updates the status."""
        access.require("verify_account", account_id)
        await self.observe(account_id, self.provider(account_id).verify())
        return self._with_credentials(self._repository.get(account_id))

    async def delete(self, access: Access, account_id: str) -> None:
        access.require("delete_account", account_id)
        self._vault.delete(account_id)
        if self._index is not None:
            self._index.forget_account(account_id)
        self._repository.delete(account_id)
        adapter = self._providers.pop(account_id, None)
        if adapter is not None:
            await adapter.close()

    async def close(self) -> None:
        """Close every adapter, e.g. when the service stops."""
        adapters, self._providers = list(self._providers.values()), {}
        for adapter in adapters:
            await adapter.close()

    def record(self, account_id: str) -> Account:
        """Internal: callers check rights first."""
        return self._repository.get(account_id)

    def status(self, account_id: str) -> AccountStatus:
        """Internal: callers check rights first."""
        return self._repository.get(account_id).status

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

    async def observe(self, account_id: str, operation: Awaitable[T]) -> T:
        """Await a provider operation and record what it says about the
        account: a rejected login needs a new credential, an unreachable
        server is marked as such, and success clears both."""
        try:
            result = await operation
        except ProviderAuthError:
            self._set_status(account_id, AccountStatus.NEEDS_REAUTH)
            raise
        except ProviderUnavailableError:
            self._set_status(account_id, AccountStatus.UNREACHABLE)
            raise
        self._set_status(account_id, AccountStatus.CONNECTED)
        return result

    def _set_status(self, account_id: str, status: AccountStatus) -> None:
        if self._repository.get(account_id).status is not status:
            self._repository.set_status(account_id, status)

    def _reader(self, account_id: str) -> CredentialReader:
        return lambda field: self._vault.read(account_id, field)

    def _with_credentials(self, account: Account) -> Account:
        return account.model_copy(update={"credentials": self._vault.info(account.id)})


def _pending(secrets: Mapping[str, SecretStr], field: str) -> SecretStr:
    try:
        return secrets[field]
    except KeyError:
        raise BadRequestError(f"the account needs the credential {field}") from None
