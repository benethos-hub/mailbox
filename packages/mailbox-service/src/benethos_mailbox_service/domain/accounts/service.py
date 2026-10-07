"""Connected accounts: create, change, verify, delete, under the caller's
rights. The live adapter of each is ``adapters``."""

from __future__ import annotations

import builtins
import re
from collections.abc import Callable, Iterable, Mapping, Sequence

from pydantic import SecretStr

from ...common import redact
from ...common.hosts import address_problem, is_server
from ...common.ids import new_id
from ...data.models import Account, AccountStatus, Page, ProviderType
from ...data.protocols import HostCheck
from ...data.providers import (
    CredentialReader,
    ProviderSettings,
    Tokens,
    hosts_in,
    settings_defaults,
)
from ...data.secrets import CredentialVault
from ...data.storage import AccountRepository, IdempotencyRepository
from ...errors import BadRequestError, MailboxServiceError, NotSupportedError
from .. import paging
from ..activity import ActivityLog, Actor
from ..activity import accounts as said
from ..changes import ChangeFeed
from ..rights import Access
from .adapters import REFRESH_TOKEN, Adapters

BY_ADDRESS = paging.Order[Account]("ac_", lambda a: (a.email.casefold(), a.id))


class AccountService:
    """Records live in the repository, credentials in the vault, the live
    adapters in ``adapters``. Every method checks the caller's right.
    ``on_delete`` hears of an account deleted, with its id: the sync
    forgets its state there. ``on_connect`` hears of an account connected,
    with the caller and its id: the caller gets ``accounts.manage`` there.
    ``on_ready`` hears of an account connected, changed or verified, with
    its id: the sync worker takes it up at once. ``offered`` are the kinds
    of account that can be connected, None for every kind. Accounts of
    other kinds connected before keep working."""

    def __init__(
        self,
        repository: AccountRepository,
        vault: CredentialVault,
        adapters: Adapters,
        on_delete: Callable[[str], None] | None = None,
        on_connect: Callable[[Access, str], None] | None = None,
        on_ready: Callable[[str], None] | None = None,
        check_host: HostCheck | None = None,
        idempotency: IdempotencyRepository | None = None,
        changes: ChangeFeed | None = None,
        activity: ActivityLog | None = None,
        offered: Iterable[ProviderType] | None = None,
    ) -> None:
        self._repository = repository
        self._activity = activity or ActivityLog()
        self._offered = frozenset(offered) if offered is not None else None
        self._vault = vault
        self._adapters = adapters
        self._on_delete = on_delete
        self._on_connect = on_connect
        self._on_ready = on_ready
        self._idempotency = idempotency
        self._changes = changes
        # Every host in an account's settings passes this before the first
        # connection: the service must not be pointed into its own network.
        self._check_host = check_host

    def list(
        self,
        access: Access,
        *,
        may: str | None = None,
        address: str | None = None,
        provider: ProviderType | None = None,
        status: AccountStatus | None = None,
    ) -> builtins.list[Account]:
        """The accounts the caller may list. With ``may``, those it may do
        that operation on as well. The others narrow the list: a part of
        the address regardless of case, the provider, the status."""
        wanted = (address or "").casefold()
        return [
            self._with_credentials(account)
            for account in self._repository.list()
            if access.allows("list_accounts", account.id)
            and (may is None or access.allows(may, account.id))
            and wanted in account.email.casefold()
            and (provider is None or account.provider is provider)
            and (status is None or account.status is status)
        ]

    def page(
        self,
        access: Access,
        *,
        limit: int,
        cursor: str | None = None,
        address: str | None = None,
        provider: ProviderType | None = None,
        status: AccountStatus | None = None,
    ) -> Page[Account]:
        """A page of ``list``, by address regardless of case."""
        found = self.list(access, address=address, provider=provider, status=status)
        return paging.page(found, BY_ADDRESS, limit=limit, cursor=cursor)

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
        if not self.offers(provider):
            raise NotSupportedError(
                f"{provider} accounts cannot be connected in this deployment"
            )
        _no_secrets_in(settings)
        settings = {**settings_defaults(provider, email), **(settings or {})}
        secrets = dict(credentials or {})
        failed = self._activity.on_failure(
            lambda exc: said.ConnectFailed(
                by=Actor.of(access),
                address=email,
                provider=provider.value,
                error=exc,
            )
        )
        with failed:
            problem = address_problem(email)
            if problem is not None:
                raise BadRequestError(problem)
            _one_line_name(display_name)
            await self._check_hosts(settings)
            if secrets:
                self._vault.require_ready()
            # A throwaway adapter that reads the credential from the
            # request. An unsupported provider or bad settings fail here,
            # before anything is stored.
            await self._probe(
                provider,
                settings,
                lambda field: _pending(secrets, field),
                secrets,
                signed_in,
            )
        account = Account(
            id=new_id("acc"),
            provider=provider,
            email=email,
            display_name=display_name,
        )
        host = settings.get("host")
        with self._activity.atomic():
            self._repository.add(account, dict(settings))
            try:
                for field, value in secrets.items():
                    self._vault.store(account.id, field, value)
            except BaseException:
                # A store without transactions keeps no half account either.
                self._vault.delete(account.id)
                self._repository.delete(account.id)
                raise
            self._activity.record(
                said.AccountConnected(
                    by=Actor.of(access),
                    account=account,
                    host=host if isinstance(host, str) else None,
                )
            )
            if self._on_connect is not None:
                self._on_connect(access, account.id)
        self._ready(account.id)
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
        create: nothing is stored unless the provider accepts it. Settings
        sent as they are stored change nothing and log in nowhere."""
        access.require("update_account", account_id)
        _no_secrets_in(settings)
        if rename:
            _one_line_name(display_name)
        account = self._repository.get(account_id)
        defaults = settings_defaults(account.provider, account.email)
        before = {**defaults, **self._repository.settings(account_id)}
        merged = _merged(before, defaults, settings or {})
        changed = merged != before
        secrets = dict(credentials or {})
        await self._check_update(account, merged, changed, secrets, signed_in)
        what = _what_changed(account, display_name, rename, changed, secrets)
        if rename:
            account = account.model_copy(update={"display_name": display_name})
        self._store_update(access, account, merged, secrets, what)
        if changed or secrets:
            # The live adapter still has the old settings: the next use
            # builds a new one.
            await self._adapters.drop(account_id)
            self._adapters.set_status(account_id, AccountStatus.CONNECTED)
            self._ready(account_id)
        return self._with_credentials(self._repository.get(account_id))

    async def _check_update(
        self,
        account: Account,
        merged: dict[str, str | int | bool],
        changed: bool,
        secrets: dict[str, SecretStr],
        signed_in: Tokens | None,
    ) -> None:
        """Log in with the changed settings and credentials before anything
        is stored, as on create."""
        # An OAuth probe may hand back a refresh token to store.
        if secrets or self.signs_in_with_oauth(account.provider):
            self._vault.require_ready()
        if changed:
            await self._check_hosts(merged)
        if not changed and not secrets:
            return

        def read(field: str) -> SecretStr:
            if field in secrets:
                return secrets[field]
            return self._vault.read(account.id, field)

        await self._probe(account.provider, merged, read, secrets, signed_in)

    def _store_update(
        self,
        access: Access,
        account: Account,
        merged: dict[str, str | int | bool],
        secrets: dict[str, SecretStr],
        what: Sequence[str],
    ) -> None:
        # The credentials first: a record that names settings the stored
        # credentials do not match would be a broken account, the reverse
        # only a credential the next probe confirms again.
        with self._activity.atomic():
            for field, secret in secrets.items():
                self._vault.store(account.id, field, secret)
            self._repository.update(account, merged)
            if what:
                self._activity.record(
                    said.AccountChanged(
                        by=Actor.of(access), account=account, changed=tuple(what)
                    )
                )

    async def verify(self, access: Access, account_id: str) -> Account:
        """Log in afresh, e.g. after the credential was changed at the
        provider. Clears a rejected login and updates the status."""
        access.require("verify_account", account_id)
        await self._adapters.call(account_id, lambda p: p.verify())
        account = self._repository.get(account_id)
        self._activity.record(
            said.AccountVerified(by=Actor.of(access), account=account)
        )
        # A rejected login left the account alone until now.
        self._ready(account_id)
        return self._with_credentials(account)

    async def delete(self, access: Access, account_id: str) -> None:
        access.require("delete_account", account_id)
        account = self._repository.get(account_id)
        with self._activity.atomic():
            self._vault.delete(account_id)
            if self._on_delete is not None:
                self._on_delete(account_id)
            if self._idempotency is not None:
                self._idempotency.forget_account(account_id)
            if self._changes is not None:
                self._changes.forget_account(account_id)
            self._repository.delete(account_id)
            self._activity.record(
                said.AccountRemoved(by=Actor.of(access), account=account)
            )
        await self._adapters.drop(account_id)

    def _ready(self, account_id: str) -> None:
        if self._on_ready is not None:
            self._on_ready(account_id)

    def offers(self, provider: ProviderType) -> bool:
        """Whether accounts of this kind can be connected here."""
        return self._offered is None or provider in self._offered

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
        for value in secrets.values():
            # Typed in just now: a failed login must not show it.
            redact.note(value.get_secret_value())
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
        any other ``*_host``. A host that is no name and no address is
        refused before it is looked up. Without a check, every other host
        passes."""
        for named in hosts_in(settings):
            if not is_server(named.host):
                raise BadRequestError(
                    f"{named.key} is not a host name or an IP address"
                )
        if self._check_host is None:
            return
        for named in hosts_in(settings):
            try:
                address = await self._check_host(named.host, named.port)
            except MailboxServiceError as exc:
                raise BadRequestError(exc.message) from None
            if address is None:
                raise BadRequestError(f"{named.key}: {named.host} does not resolve")

    def _with_credentials(self, account: Account) -> Account:
        """The account as callers see it: which credentials are stored, and
        its settings."""
        return account.model_copy(
            update={
                "credentials": self._vault.info(account.id),
                "settings": self._repository.settings(account.id),
                "capabilities": self._adapters.offered(account.id),
            }
        )


# The display name goes into the From of every send, on one line, and
# into the log. No line break, no other control character.
_NOT_IN_NAME = re.compile(r"[\x00-\x1f\x7f\x85\u2028\u2029]")
LONGEST_NAME = 200


def _one_line_name(name: str | None) -> None:
    if name is None:
        return
    if len(name) > LONGEST_NAME:
        raise BadRequestError(
            f"the display name is longer than {LONGEST_NAME} characters"
        )
    if _NOT_IN_NAME.search(name):
        raise BadRequestError(
            "the display name must not hold a line break or a control character"
        )


# Settings are returned to callers. A secret belongs in the credentials,
# which never are.
_SECRET_WORDS = ("password", "secret", "token", "credential", "apikey", "api_key")


def _merged(
    before: dict[str, str | int | bool],
    defaults: Mapping[str, str | int | bool],
    settings: Mapping[str, str | int | bool | None],
) -> dict[str, str | int | bool]:
    """The settings with the changes. A setting removed falls back to
    what the provider assumes."""
    merged = dict(before)
    for key, value in settings.items():
        if value is None:
            merged.pop(key, None)
            if key in defaults:
                merged[key] = defaults[key]
        else:
            merged[key] = value
    return merged


def _what_changed(
    account: Account,
    display_name: str | None,
    rename: bool,
    changed: bool,
    secrets: Mapping[str, SecretStr],
) -> list[str]:
    """What an update changes, for the audit: never a secret's value."""
    what = []
    if rename and display_name != account.display_name:
        what.append("display name")
    if changed:
        what.append("settings")
    return what + sorted(secrets)


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
