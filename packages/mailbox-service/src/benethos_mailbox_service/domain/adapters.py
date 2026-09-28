"""The live adapter of each account, and calls through it.

Records live in the repository, credentials in the vault. This holds the
one adapter per account, builds it on first use and keeps the account's
status in step with how each call went. It checks no rights: the services
that use it do, and hand it accounts the caller may act on.
"""

from __future__ import annotations

import builtins
from collections.abc import Awaitable, Callable, Mapping
from typing import TypeVar

from pydantic import SecretStr

from ..data.models import Account, AccountStatus, ProviderType
from ..data.providers import (
    Capability,
    CredentialReader,
    MailProvider,
    OAuthClient,
    ProviderFactory,
    ProviderSettings,
    RefreshingTokens,
    Tokens,
    TokenSource,
    build_provider,
)
from ..data.secrets import CredentialVault
from ..data.storage import AccountRepository
from ..errors import ProviderAuthError, ProviderUnavailableError
from .activity import SERVICE, Activity, ActivityLog
from .activity.catalogue import accounts as said
from .changes import ChangeFeed

T = TypeVar("T")

# The credential of an OAuth account: its refresh token.
REFRESH_TOKEN = "refresh_token"


class Adapters:
    def __init__(
        self,
        repository: AccountRepository,
        vault: CredentialVault,
        provider_factory: ProviderFactory = build_provider,
        oauth: Mapping[ProviderType, OAuthClient] | None = None,
        changes: ChangeFeed | None = None,
        activity: ActivityLog | None = None,
    ) -> None:
        self._repository = repository
        self._activity = activity or ActivityLog()
        # Hears when an account comes to need a new sign-in.
        self._changes = changes
        self._vault = vault
        self._provider_factory = provider_factory
        # The OAuth app of each provider that signs in with OAuth, where the
        # operator registered one.
        self._oauth = dict(oauth or {})
        self._providers: dict[str, MailProvider] = {}
        # The status as last read or written, so a call does not read the
        # record again to see whether it changed.
        self._status: dict[str, AccountStatus] = {}

    # --- the records, without a rights check ----------------------------------------

    def record(self, account_id: str) -> Account:
        return self._repository.get(account_id)

    def ids(self) -> builtins.list[str]:
        """Every account id. Callers filter by rights themselves."""
        return [account.id for account in self._repository.list()]

    def status(self, account_id: str) -> AccountStatus:
        status = self._status.get(account_id)
        if status is None:
            status = self._status[account_id] = self.record(account_id).status
        return status

    def set_status(
        self, account_id: str, status: AccountStatus, reason: str | None = None
    ) -> None:
        """A new status is stored and logged once, when it changes.
        ``reason``: the message of the failure that changed it."""
        if self.status(account_id) is not status:
            self._repository.set_status(account_id, status)
            self._status[account_id] = status
            if status is AccountStatus.NEEDS_REAUTH and self._changes is not None:
                self._changes.record(account_id, "account.needs_reauth", [account_id])
            self._activity.record(self._flipped(account_id, status, reason))

    def _flipped(
        self, account_id: str, status: AccountStatus, reason: str | None
    ) -> Activity:
        account = self.record(account_id)
        if status is AccountStatus.NEEDS_REAUTH:
            return said.AccountNeedsSignIn(by=SERVICE, account=account, reason=reason)
        if status is AccountStatus.UNREACHABLE:
            return said.AccountUnreachable(by=SERVICE, account=account, reason=reason)
        return said.AccountReachable(by=SERVICE, account=account)

    def signs_in_with_oauth(self, provider: ProviderType) -> bool:
        """Whether accounts of ``provider`` connect through an OAuth app of
        this deployment."""
        return provider in self._oauth

    # --- the adapters ---------------------------------------------------------------

    def get(self, account_id: str) -> MailProvider:
        """The adapter of an account, built on first use after a restart."""
        adapter = self._providers.get(account_id)
        if adapter is None:
            account = self.record(account_id)
            adapter = self.build(
                account.provider,
                self._repository.settings(account_id),
                lambda field: self._vault.read(account_id, field),
                lambda value: self._vault.store(account_id, REFRESH_TOKEN, value),
                on_refresh=lambda: self._activity.record(
                    said.TokenRefreshed(by=SERVICE, account=account)
                ),
            )
            self._providers[account_id] = adapter
        return adapter

    def capabilities(self, account_id: str) -> frozenset[Capability]:
        return self.get(account_id).capabilities

    async def call(
        self, account_id: str, operation: Callable[[MailProvider], Awaitable[T]]
    ) -> T:
        """Run one operation on the account's adapter and record what it
        says about the account: a rejected login needs a new credential, an
        unreachable server is marked as such, and success clears both."""
        try:
            result = await operation(self.get(account_id))
        except ProviderAuthError as exc:
            self.set_status(account_id, AccountStatus.NEEDS_REAUTH, exc.message)
            raise
        except ProviderUnavailableError as exc:
            self.set_status(account_id, AccountStatus.UNREACHABLE, exc.message)
            raise
        self.set_status(account_id, AccountStatus.CONNECTED)
        return result

    def build(
        self,
        provider: ProviderType,
        settings: ProviderSettings,
        read: CredentialReader,
        store_refresh: Callable[[SecretStr], None],
        signed_in: Tokens | None = None,
        on_refresh: Callable[[], object] | None = None,
    ) -> MailProvider:
        """An adapter. For an OAuth provider it comes with a token source that
        keeps its access token valid and stores a new refresh token.
        ``signed_in``: the tokens of a sign-in just made, used before the
        first refresh. ``on_refresh`` hears of each refresh."""
        client = self._oauth.get(provider)
        if client is None:
            return self._provider_factory(provider, settings, read)
        tokens: TokenSource = RefreshingTokens(
            client,
            lambda: read(REFRESH_TOKEN),
            store_refresh,
            current=signed_in,
            on_refresh=on_refresh,
        )
        return self._provider_factory(provider, settings, read, tokens=tokens)

    async def drop(self, account_id: str) -> None:
        """Forget the adapter and what is known of the account: the next
        use reads the record and builds a new one."""
        self._status.pop(account_id, None)
        adapter = self._providers.pop(account_id, None)
        if adapter is not None:
            await adapter.close()

    async def close(self) -> None:
        """Close every adapter, e.g. when the service stops."""
        adapters, self._providers = list(self._providers.values()), {}
        self._status.clear()
        for adapter in adapters:
            await adapter.close()
