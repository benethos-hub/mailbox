"""Connected accounts: create, change, verify, delete, under the caller's
rights. The live adapter of each is ``adapters``."""

from __future__ import annotations

import builtins
from collections.abc import Mapping

from pydantic import SecretStr

from ..common.ids import new_id
from ..data.http import HostCheck
from ..data.models import Account, AccountStatus, ProviderType
from ..data.providers import (
    CredentialReader,
    ProviderSettings,
    Tokens,
    hosts_in,
    settings_defaults,
)
from ..data.secrets import CredentialVault
from ..data.storage import AccountRepository, MessageIndexRepository
from ..errors import BadRequestError, MailboxServiceError
from .access import Access
from .adapters import REFRESH_TOKEN, Adapters


class AccountService:
    """Records live in the repository, credentials in the vault, the live
    adapters in ``adapters``. Every method checks the caller's right."""

    def __init__(
        self,
        repository: AccountRepository,
        vault: CredentialVault,
        adapters: Adapters,
        index: MessageIndexRepository | None = None,
        check_host: HostCheck | None = None,
    ) -> None:
        self._repository = repository
        self._vault = vault
        self._adapters = adapters
        self._index = index
        # Every host in an account's settings passes this before the first
        # connection: the service must not be pointed into its own network.
        self._check_host = check_host

    def list(self, access: Access, *, may: str | None = None) -> builtins.list[Account]:
        """The accounts the caller may list. With ``may``, those it may do
        that operation on as well."""
        return [
            self._with_credentials(account)
            for account in self._repository.list()
            if access.allows("list_accounts", account.id)
            and (may is None or access.allows(may, account.id))
        ]

    def get(self, access: Access, account_id: str) -> Account:
        access.require("get_account", account_id)
        return self._with_credentials(self._repository.get(account_id))

    def visible(self, access: Access, account_id: str) -> Account:
        """The account as whoever may do anything on it sees it, as in
        ``/v1/me``: whoever may only write drafts there sees its address."""
        if not access.operations_on(account_id):
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
        signed_in: Tokens | None = None,
    ) -> Account:
        """Verify, then store: nothing is kept unless the provider accepts the
        credential. ``signed_in``: the tokens of an OAuth sign-in, used for
        the check instead of a refresh."""
        access.require("create_account")
        _no_secrets_in(settings)
        settings = {**settings_defaults(provider, email), **(settings or {})}
        await self._check_hosts(settings)
        secrets = dict(credentials or {})
        if secrets:
            self._vault.require_ready()
        account = Account(
            id=new_id("acc"),
            provider=provider,
            email=email,
            display_name=display_name,
        )
        # A throwaway adapter that reads the credential from the request. An
        # unsupported provider or bad settings fail here, before anything is
        # stored.
        await self._probe(
            provider,
            settings,
            lambda field: _pending(secrets, field),
            secrets,
            signed_in,
        )
        self._repository.add(account, dict(settings))
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
        signed_in: Tokens | None = None,
    ) -> Account:
        """Change the display name, settings (``None`` removes one) or
        credentials. A change of settings or credentials logs in first, as on
        create: nothing is stored unless the provider accepts it."""
        access.require("update_account", account_id)
        _no_secrets_in(settings)
        account = self._repository.get(account_id)
        merged: dict[str, str | int | bool] = dict(
            self._repository.settings(account_id)
        )
        for key, value in (settings or {}).items():
            if value is None:
                merged.pop(key, None)
            else:
                merged[key] = value
        # A setting removed falls back to what the provider assumes.
        for key, value in settings_defaults(account.provider, account.email).items():
            merged.setdefault(key, value)
        secrets = dict(credentials or {})
        # An OAuth probe may hand back a refresh token to store.
        if secrets or self.signs_in_with_oauth(account.provider):
            self._vault.require_ready()
        if settings:
            await self._check_hosts(merged)
        if settings or secrets:

            def read(field: str) -> SecretStr:
                if field in secrets:
                    return secrets[field]
                return self._vault.read(account_id, field)

            await self._probe(account.provider, merged, read, secrets, signed_in)
        if rename:
            account = account.model_copy(update={"display_name": display_name})
        # The credentials first: a record that names settings the stored
        # credentials do not match would be a broken account, the reverse
        # only a credential the next probe confirms again.
        for field, secret in secrets.items():
            self._vault.store(account_id, field, secret)
        self._repository.update(account, merged)
        if settings or secrets:
            # The live adapter still has the old settings: the next use
            # builds a new one.
            await self._adapters.drop(account_id)
            self._adapters.set_status(account_id, AccountStatus.CONNECTED)
        return self._with_credentials(self._repository.get(account_id))

    async def verify(self, access: Access, account_id: str) -> Account:
        """Log in afresh, e.g. after the credential was changed at the
        provider. Clears a rejected login and updates the status."""
        access.require("verify_account", account_id)
        await self._adapters.call(account_id, lambda p: p.verify())
        return self._with_credentials(self._repository.get(account_id))

    async def delete(self, access: Access, account_id: str) -> None:
        access.require("delete_account", account_id)
        self._vault.delete(account_id)
        if self._index is not None:
            self._index.forget_account(account_id)
        self._repository.delete(account_id)
        await self._adapters.drop(account_id)

    def signs_in_with_oauth(self, provider: ProviderType) -> bool:
        """Whether accounts of ``provider`` connect through an OAuth app of
        this deployment."""
        return self._adapters.signs_in_with_oauth(provider)

    async def _probe(
        self,
        provider: ProviderType,
        settings: ProviderSettings,
        read: CredentialReader,
        secrets: dict[str, SecretStr],
        signed_in: Tokens | None = None,
    ) -> None:
        """Log in once with a throwaway adapter. A refresh token it is
        handed lands in ``secrets``, to be stored with the rest."""
        probe = self._adapters.build(
            provider,
            settings,
            read,
            lambda value: secrets.__setitem__(REFRESH_TOKEN, value),
            signed_in,
        )
        try:
            await probe.verify()
        finally:
            await probe.close()

    async def _check_hosts(self, settings: Mapping[str, object]) -> None:
        """Refuse settings that point the service at a host it may not
        connect to, before any adapter is built: ``host``, ``smtp_host`` and
        any other ``*_host``. Without a check, every host passes."""
        if self._check_host is None:
            return
        for key, host, port in hosts_in(settings):
            try:
                address = await self._check_host(host, port)
            except MailboxServiceError as exc:
                raise BadRequestError(exc.message) from None
            if address is None:
                raise BadRequestError(f"{key}: {host} does not resolve")

    def _with_credentials(self, account: Account) -> Account:
        """The account as callers see it: which credentials are stored, and
        its settings."""
        return account.model_copy(
            update={
                "credentials": self._vault.info(account.id),
                "settings": self._repository.settings(account.id),
            }
        )


# Settings are returned to callers. A secret belongs in the credentials,
# which never are.
_SECRET_WORDS = ("password", "secret", "token", "credential", "apikey", "api_key")


def _no_secrets_in(settings: Mapping[str, object] | None) -> None:
    for key in settings or {}:
        if any(word in key.lower().replace("-", "_") for word in _SECRET_WORDS):
            raise BadRequestError(
                f"{key} looks like a secret: pass it in credentials, which are "
                "stored encrypted and never returned, not in settings"
            )


def _pending(secrets: Mapping[str, SecretStr], field: str) -> SecretStr:
    try:
        return secrets[field]
    except KeyError:
        raise BadRequestError(f"the account needs the credential {field}") from None
