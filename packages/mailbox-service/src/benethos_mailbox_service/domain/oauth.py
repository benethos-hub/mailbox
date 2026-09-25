"""Connecting an account by OAuth: the sign-in at the provider, and back.

``start`` gives the address to send the browser to. The provider sends it
back with a code, and ``finish`` turns the code into a connected account,
or signs an existing one in again. The web layer only carries the browser
there and back.

Rules:

- ``state`` is random, used once, valid for ten minutes and bound to the
  user who started. A code that comes back for someone else is refused.
- Connecting needs ``create_account``, signing in again ``update_account``
  on that account, as with a password.
- Signing in again must bring back the same address: otherwise another
  mailbox would slip in under an existing account.
- Only the refresh token is stored, in the vault. The access token stays
  in memory (CONCEPT 7.3).
"""

from __future__ import annotations

import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from ..common.clock import utc_now
from ..data.models import Account, ProviderType
from ..data.providers import OAuthClient, authorize_url, new_pkce
from ..errors import BadRequestError, ForbiddenError, NotSupportedError
from .access import Access
from .accounts import AccountService
from .adapters import REFRESH_TOKEN, Adapters

VALID_FOR = timedelta(minutes=10)
# Sign-ins a user may have open at once. Older ones are dropped.
OPEN_PER_USER = 5


@dataclass(frozen=True)
class _Pending:
    provider: ProviderType
    user_id: str
    verifier: str
    redirect_uri: str
    started: datetime
    # The account when signing in again, None to connect a new one.
    account_id: str | None


class OAuthService:
    def __init__(
        self,
        accounts: AccountService,
        adapters: Adapters,
        clients: Mapping[ProviderType, OAuthClient],
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._accounts = accounts
        self._adapters = adapters
        self._clients = dict(clients)
        self._clock = clock
        self._pending: dict[str, _Pending] = {}

    def providers(self) -> list[ProviderType]:
        """The providers this deployment has an OAuth app for."""
        return sorted(self._clients, key=str)

    def start(
        self,
        access: Access,
        provider: ProviderType,
        redirect_uri: str,
        *,
        account_id: str | None = None,
        login_hint: str | None = None,
    ) -> str:
        """Where to send the browser to sign in: to connect a new account,
        or with ``account_id`` to sign that account in again."""
        client = self._client(provider)
        if account_id is None:
            access.require("create_account")
        else:
            access.require("update_account", account_id)
            account = self._adapters.record(account_id)
            if account.provider is not provider:
                raise BadRequestError(
                    f"{account.email} is a {account.provider} account, not {provider}"
                )
            login_hint = login_hint or account.email
        self._forget_old(access.user_id)
        state = secrets.token_urlsafe(32)
        pkce = new_pkce()
        self._pending[state] = _Pending(
            provider=provider,
            user_id=access.user_id,
            verifier=pkce.verifier,
            redirect_uri=redirect_uri,
            started=self._clock(),
            account_id=account_id,
        )
        return authorize_url(client.app, redirect_uri, state, pkce, login_hint)

    async def finish(
        self, access: Access, provider: ProviderType, state: str, code: str
    ) -> Account:
        """The account the sign-in connected, or signed in again."""
        pending = self._pending.pop(state, None)
        if (
            pending is None
            or pending.provider is not provider
            or self._clock() - pending.started > VALID_FOR
        ):
            raise BadRequestError("this sign-in is unknown or expired: start again")
        if pending.user_id != access.user_id:
            raise ForbiddenError("this sign-in was started by someone else")
        client = self._client(provider)
        tokens = await client.exchange(code, pending.redirect_uri, pending.verifier)
        if tokens.refresh_token is None:
            raise BadRequestError(
                f"{provider} gave no refresh token: the app must ask for offline_access"
            )
        email = tokens.identity.email if tokens.identity else None
        if not email:
            raise BadRequestError(f"{provider} did not say which address signed in")
        credentials = {REFRESH_TOKEN: tokens.refresh_token}
        if pending.account_id is not None:
            existing = self._accounts.get(access, pending.account_id)
            if existing.email.lower() != email:
                raise BadRequestError(
                    f"signed in as {email}, but the account is {existing.email}: "
                    "sign in with that address"
                )
            return await self._accounts.update(
                access,
                pending.account_id,
                display_name=None,
                rename=False,
                credentials=credentials,
                signed_in=tokens,
            )
        name = tokens.identity.name if tokens.identity else None
        return await self._accounts.create(
            access,
            provider,
            email,
            name,
            credentials=credentials,
            signed_in=tokens,
        )

    def cancel(self, state: str) -> None:
        """The provider sent back an error instead of a code."""
        self._pending.pop(state, None)

    def sign_in_hosts(self) -> list[str]:
        """The hosts a browser is sent to for a sign-in."""
        return sorted(
            {
                urlsplit(client.app.endpoints.authorize_url).netloc
                for client in self._clients.values()
            }
        )

    def _client(self, provider: ProviderType) -> OAuthClient:
        client = self._clients.get(provider)
        if client is None:
            raise NotSupportedError(
                f"no OAuth app for {provider} is set up in this deployment"
            )
        return client

    def _forget_old(self, user_id: str) -> None:
        """Drop expired sign-ins, and the oldest of this user's beyond the
        limit."""
        now = self._clock()
        for state, pending in list(self._pending.items()):
            if now - pending.started > VALID_FOR:
                del self._pending[state]
        mine = sorted(
            (p.started, s) for s, p in self._pending.items() if p.user_id == user_id
        )
        for _, state in mine[: max(0, len(mine) - OPEN_PER_USER + 1)]:
            del self._pending[state]
