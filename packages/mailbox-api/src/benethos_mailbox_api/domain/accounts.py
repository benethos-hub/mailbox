"""Connected accounts and the live adapter behind each."""

from __future__ import annotations

import uuid

from ..data.models import Account, ProviderType
from ..data.providers import (
    MailProvider,
    ProviderFactory,
    ProviderSettings,
    build_provider,
)
from ..data.storage import AccountRepository
from .access import Access


class AccountService:
    """Owns the one adapter per account. Records live in the repository."""

    def __init__(
        self,
        repository: AccountRepository,
        provider_factory: ProviderFactory = build_provider,
    ) -> None:
        self._repository = repository
        self._provider_factory = provider_factory
        self._providers: dict[str, MailProvider] = {}

    def list(self, access: Access) -> list[Account]:
        return [
            account
            for account in self._repository.list()
            if access.allows("list_accounts", account.id)
        ]

    def get(self, access: Access, account_id: str) -> Account:
        access.require("get_account", account_id)
        return self._repository.get(account_id)

    def create(
        self,
        access: Access,
        provider: ProviderType,
        email: str,
        display_name: str | None = None,
        settings: ProviderSettings | None = None,
    ) -> Account:
        access.require("create_account")
        account = Account(
            id=f"acc_{uuid.uuid4().hex[:12]}",
            provider=provider,
            email=email,
            display_name=display_name,
        )
        # The adapter first: an unsupported provider leaves no record behind.
        adapter = self._provider_factory(provider, settings or {})
        self._repository.add(account)
        self._providers[account.id] = adapter
        return account

    async def delete(self, access: Access, account_id: str) -> None:
        access.require("delete_account", account_id)
        self._repository.delete(account_id)
        adapter = self._providers.pop(account_id, None)
        if adapter is not None:
            await adapter.close()

    def provider(self, account_id: str) -> MailProvider:
        """The adapter of an account. Internal: callers check rights first."""
        self._repository.get(account_id)
        return self._providers[account_id]
