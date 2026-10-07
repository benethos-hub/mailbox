"""Connecting an account by OAuth: the sign-in at the provider, and back.

Two ways. ``start`` gives the address to send the browser to. The provider
sends it back with a code, and ``finish`` turns the code into a connected
account, or signs an existing one in again. The web layer only carries the
browser there and back. Or ``start_device`` gives a code that the person
enters at the provider, on any device, and ``poll_device`` connects the
account once they signed in. That way needs no address the provider sends
a browser back to: the project's own app, a public client, is sent back
to localhost only.

Rules:

- A sign-in is random, used once and bound to the user who started it.
  One that comes back for someone else is refused. One in the browser is
  valid for ten minutes, one with a code as long as the provider says.
- Connecting needs ``create_account`` and a kind of account this
  deployment offers. Signing in again needs ``update_account`` on that
  account, as with a password, whatever kinds are offered.
- Signing in again must bring back the same address: otherwise another
  mailbox would slip in under an existing account.
- A sign-in with a code asks the provider no more often than it allows.
- Only the refresh token is stored, in the vault. The access token stays
  in memory (CONCEPT 7.3).
"""

from __future__ import annotations

import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from ...common.clock import utc_now
from ...data.models import Account, ProviderType
from ...data.providers import (
    DeviceCode,
    OAuthClient,
    Tokens,
    Waiting,
    authorize_url,
    new_pkce,
)
from ...errors import BadRequestError, NotSupportedError
from ..activity import ActivityLog, Actor
from ..activity import accounts as said
from ..rights import Access
from .adapters import REFRESH_TOKEN, Adapters
from .service import AccountService

VALID_FOR = timedelta(minutes=10)
# A code is valid as long as the provider says, but no longer than this.
DEVICE_VALID_FOR = timedelta(minutes=30)
# What a provider that asks to be asked less often adds to the interval.
SLOWER = timedelta(seconds=5)
# Sign-ins a user may have open at once, each way. Older ones are dropped.
OPEN_PER_USER = 5

_UNKNOWN = "this sign-in is unknown or expired: start again"


@dataclass(frozen=True)
class _Pending:
    provider: ProviderType
    user_id: str
    verifier: str
    redirect_uri: str
    started: datetime
    # The account when signing in again, None to connect a new one.
    account_id: str | None


@dataclass(frozen=True)
class DeviceSignIn:
    """A sign-in with a code: the person enters ``user_code`` at
    ``verification_uri``, then ``poll_device`` with ``id`` connects the
    account. ``interval`` is the seconds between two polls that are worth
    it."""

    id: str
    provider: ProviderType
    user_code: str
    verification_uri: str
    expires_at: datetime
    interval: int


@dataclass
class _Device:
    provider: ProviderType
    user_id: str
    code: DeviceCode
    shown: DeviceSignIn
    started: datetime
    expires_at: datetime
    # The account when signing in again, None to connect a new one.
    account_id: str | None
    # The provider is not asked again before this.
    next_at: datetime
    interval: timedelta
    # A question to the provider is out, or the account is being connected.
    asking: bool = False
    # The account, once connected: a later poll answers with it again.
    done: Account | None = None


class OAuthService:
    def __init__(
        self,
        accounts: AccountService,
        adapters: Adapters,
        clients: Mapping[ProviderType, OAuthClient],
        clock: Callable[[], datetime] = utc_now,
        activity: ActivityLog | None = None,
    ) -> None:
        self._accounts = accounts
        self._adapters = adapters
        self._clients = dict(clients)
        self._clock = clock
        self._activity = activity or ActivityLog(clock)
        self._pending: dict[str, _Pending] = {}
        self._devices: dict[str, _Device] = {}

    def providers(self) -> list[ProviderType]:
        """The providers a new account can sign in with here: this
        deployment has an OAuth app for them and offers their accounts."""
        return sorted((p for p in self._clients if self._accounts.offers(p)), key=str)

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
        account = self._checked(access, provider, account_id)
        if account is not None:
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
        self._activity.record(
            said.OAuthStarted(
                by=Actor.of(access), provider=provider.value, account=account
            )
        )
        return authorize_url(client.app, redirect_uri, state, pkce, login_hint)

    async def finish(
        self, access: Access, provider: ProviderType, state: str, code: str
    ) -> Account:
        """The account the sign-in connected, or signed in again. Another
        user's sign-in answers as an unknown one and stays open for its
        owner."""
        failed = self._activity.on_failure(
            lambda exc: said.OAuthFailed(
                by=Actor.of(access), provider=provider.value, error=exc
            )
        )
        with failed:
            account, again = await self._finish(access, provider, state, code)
        self._finished(access, provider, account, again)
        return account

    async def _finish(
        self, access: Access, provider: ProviderType, state: str, code: str
    ) -> tuple[Account, bool]:
        """The account, and whether it signed in again."""
        pending = self._pending.get(state)
        if pending is None or pending.user_id != access.user_id:
            raise BadRequestError(_UNKNOWN)
        del self._pending[state]
        if (
            pending.provider is not provider
            or self._clock() - pending.started > VALID_FOR
        ):
            raise BadRequestError(_UNKNOWN)
        client = self._client(provider)
        tokens = await client.exchange(code, pending.redirect_uri, pending.verifier)
        return await self._connect(access, provider, tokens, pending.account_id)

    async def start_device(
        self,
        access: Access,
        provider: ProviderType,
        *,
        account_id: str | None = None,
    ) -> DeviceSignIn:
        """A code to sign in with at the provider, on any device: to connect
        a new account, or with ``account_id`` to sign that account in
        again. ``poll_device`` then connects it."""
        client = self._client(provider)
        account = self._checked(access, provider, account_id)
        self._forget_old(access.user_id)
        code = await client.device_code()
        now = self._clock()
        interval = timedelta(seconds=code.interval)
        sign_in_id = secrets.token_urlsafe(32)
        expires_at = now + min(timedelta(seconds=code.expires_in), DEVICE_VALID_FOR)
        shown = DeviceSignIn(
            id=sign_in_id,
            provider=provider,
            user_code=code.user_code,
            verification_uri=code.verification_uri,
            expires_at=expires_at,
            interval=code.interval,
        )
        self._devices[sign_in_id] = _Device(
            provider=provider,
            user_id=access.user_id,
            code=code,
            shown=shown,
            started=now,
            expires_at=expires_at,
            account_id=account_id,
            next_at=now + interval,
            interval=interval,
        )
        self._activity.record(
            said.OAuthStarted(
                by=Actor.of(access), provider=provider.value, account=account
            )
        )
        return shown

    def device(
        self, access: Access, provider: ProviderType, sign_in_id: str
    ) -> DeviceSignIn:
        """A sign-in with a code this user started, as ``start_device``
        answered it."""
        return self._device(access, provider, sign_in_id).shown

    def _device(
        self, access: Access, provider: ProviderType, sign_in_id: str
    ) -> _Device:
        device = self._devices.get(sign_in_id)
        if (
            device is None
            or device.user_id != access.user_id
            or device.provider is not provider
        ):
            raise BadRequestError(_UNKNOWN)
        return device

    async def poll_device(
        self, access: Access, provider: ProviderType, sign_in_id: str
    ) -> Account | None:
        """The account once the person signed in with the code, None until
        then. A poll before the provider's interval has passed answers None
        without asking it. Another user's sign-in answers as an unknown
        one."""
        device = self._device(access, provider, sign_in_id)
        if device.done is not None:
            return device.done
        now = self._clock()
        if now > device.expires_at:
            del self._devices[sign_in_id]
            raise BadRequestError(f"the code for {provider} has expired: start again")
        if device.asking or now < device.next_at:
            return None
        device.asking = True
        failed = self._activity.on_failure(
            lambda exc: said.OAuthFailed(
                by=Actor.of(access), provider=provider.value, error=exc
            )
        )
        try:
            with failed:
                answer = await self._client(provider).poll_device(
                    device.code.device_code
                )
                if isinstance(answer, Waiting):
                    if answer.slow_down:
                        device.interval += SLOWER
                    device.next_at = self._clock() + device.interval
                    return None
                account, again = await self._connect(
                    access, provider, answer, device.account_id
                )
        except Exception:
            # Declined, expired, or the account refused: start again.
            self._devices.pop(sign_in_id, None)
            raise
        finally:
            device.asking = False
        device.done = account
        self._finished(access, provider, account, again)
        return account

    async def _connect(
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

    def _finished(
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

    def cancel(self, access: Access, state: str, reason: str | None = None) -> bool:
        """The provider sent back an error instead of a code, ``reason``.
        Only whoever started the sign-in can end it this way. True when it
        was one."""
        pending = self._pending.get(state)
        if pending is not None and pending.user_id == access.user_id:
            del self._pending[state]
            self._activity.record(
                said.OAuthFailed(
                    by=Actor.of(access),
                    provider=pending.provider.value,
                    error=BadRequestError(reason or "the provider sent back an error"),
                )
            )
            return True
        return False

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

    def _checked(
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

    def _forget_old(self, user_id: str) -> None:
        """Drop expired sign-ins, and the oldest of this user's beyond the
        limit, each way."""
        now = self._clock()
        for state, pending in list(self._pending.items()):
            if now - pending.started > VALID_FOR:
                del self._pending[state]
        for sign_in_id, device in list(self._devices.items()):
            if now > device.expires_at:
                del self._devices[sign_in_id]
        for open_ in (self._pending, self._devices):
            mine = sorted(
                (p.started, key) for key, p in open_.items() if p.user_id == user_id
            )
            for _, key in mine[: max(0, len(mine) - OPEN_PER_USER + 1)]:
                del open_[key]
