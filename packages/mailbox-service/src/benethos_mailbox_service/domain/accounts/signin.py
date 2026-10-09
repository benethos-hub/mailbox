"""What both ways of an OAuth sign-in share: the app of each provider,
whether the caller may start one, the account the tokens connect or sign
in again, and what the log is told.

The ways themselves are ``oauth`` (in the browser) and ``device`` (with
a code).
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import datetime
from typing import Protocol, TypeVar

from ...data.models import Account, ProviderType
from ...data.providers import OAuthClient, Tokens
from ...errors import BadRequestError, NotSupportedError
from ..activity import ActivityLog, Actor
from ..activity import accounts as said
from ..rights import Access
from .adapters import REFRESH_TOKEN, Adapters
from .service import AccountService

# Sign-ins a user may have open at once, each way. Older ones are dropped.
OPEN_PER_USER = 5

UNKNOWN = "this sign-in is unknown or expired: start again"


class Opened(Protocol):
    """A sign-in started and not finished yet, either way."""

    @property
    def user_id(self) -> str: ...

    @property
    def started(self) -> datetime: ...


OpenedT = TypeVar("OpenedT", bound=Opened)


def forget_beyond(opened: dict[str, OpenedT], user_id: str) -> None:
    """Drop the oldest of the user's open sign-ins beyond the limit, with
    room for one more."""
    mine = sorted((p.started, key) for key, p in opened.items() if p.user_id == user_id)
    for _, key in mine[: max(0, len(mine) - OPEN_PER_USER + 1)]:
        del opened[key]


class SignIns:
    """The steps of a sign-in that do not depend on its way."""

    def __init__(
        self,
        accounts: AccountService,
        adapters: Adapters,
        clients: dict[ProviderType, OAuthClient],
        activity: ActivityLog,
    ) -> None:
        self._accounts = accounts
        self._adapters = adapters
        self._clients = clients
        self._activity = activity

    def client(self, provider: ProviderType) -> OAuthClient:
        client = self._clients.get(provider)
        if client is None:
            raise NotSupportedError(
                f"no OAuth app for {provider} is set up in this deployment"
            )
        return client

    def checked(
        self, access: Access, provider: ProviderType, account_id: str | None
    ) -> Account | None:
        """The account to sign in again, None to connect a new one, once
        the caller may."""
        if account_id is None:
            access.require("create_account")
            if not self._accounts.offers(provider):
                raise NotSupportedError(
                    f"{provider} accounts cannot be connected in this deployment"
                )
            return None
        access.require("update_account", account_id)
        account = self._adapters.record(account_id)
        if account.provider is not provider:
            raise BadRequestError(
                f"{account.email} is a {account.provider} account, not {provider}"
            )
        return account

    def started(
        self, access: Access, provider: ProviderType, account: Account | None
    ) -> None:
        self._activity.record(
            said.OAuthStarted(
                by=Actor.of(access), provider=provider.value, account=account
            )
        )

    def failing(
        self, access: Access, provider: ProviderType
    ) -> AbstractContextManager[None]:
        """A failure of ours in the block, told to the log and raised on."""
        return self._activity.on_failure(
            lambda exc: said.OAuthFailed(
                by=Actor.of(access), provider=provider.value, error=exc
            )
        )

    async def connect(
        self,
        access: Access,
        provider: ProviderType,
        tokens: Tokens,
        account_id: str | None,
    ) -> tuple[Account, bool]:
        """The account the tokens connect, or ``account_id`` signed in
        again, and whether it signed in again."""
        if tokens.refresh_token is None:
            raise BadRequestError(
                f"{provider} gave no refresh token: the app must ask for offline_access"
            )
        email = tokens.identity.email if tokens.identity else None
        if not email:
            raise BadRequestError(f"{provider} did not say which address signed in")
        credentials = {REFRESH_TOKEN: tokens.refresh_token}
        if account_id is not None:
            # The start checked update_account. The record is read the same
            # way, not through a read right the caller may lack.
            existing = self._adapters.record(account_id)
            if existing.email.lower() != email:
                raise BadRequestError(
                    f"signed in as {email}, but the account is {existing.email}: "
                    "sign in with that address"
                )
            updated = await self._accounts.update(
                access,
                account_id,
                display_name=None,
                rename=False,
                credentials=credentials,
                signed_in=tokens,
            )
            return updated, True
        name = tokens.identity.name if tokens.identity else None
        created = await self._accounts.create(
            access,
            provider,
            email,
            name,
            credentials=credentials,
            signed_in=tokens,
        )
        return created, False

    def finished(
        self, access: Access, provider: ProviderType, account: Account, again: bool
    ) -> None:
        self._activity.record(
            said.OAuthFinished(
                by=Actor.of(access),
                provider=provider.value,
                account=account,
                again=again,
            )
        )
