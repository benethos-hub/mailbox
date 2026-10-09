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

The way in the browser is here. What both ways share is ``signin``, the
way with a code ``device``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from ...common.clock import utc_now
from ...common.secret import token
from ...common.urls import is_loopback
from ...data.models import Account, ProviderType
from ...data.providers import OAuthClient, authorize_url, new_pkce
from ...errors import BadRequestError
from ..activity import ActivityLog, Actor
from ..activity import accounts as said
from ..rights import Access
from .adapters import Adapters
from .device import DeviceSignIn, DeviceSignIns
from .service import AccountService
from .signin import UNKNOWN, SignIns, forget_beyond

VALID_FOR = timedelta(minutes=10)


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
        activity: ActivityLog | None = None,
    ) -> None:
        self._accounts = accounts
        self._clients = dict(clients)
        self._clock = clock
        self._activity = activity or ActivityLog(clock)
        self._sign_ins = SignIns(accounts, adapters, self._clients, self._activity)
        self._pending: dict[str, _Pending] = {}
        self._devices = DeviceSignIns(self._sign_ins, clock)

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
        client = self._sign_ins.client(provider)
        account = self._sign_ins.checked(access, provider, account_id)
        if not self.in_browser(provider, redirect_uri):
            raise BadRequestError(
                f"{provider} sends a browser back to this service only at "
                "localhost with the project's app: sign in with a code"
            )
        if account is not None:
            login_hint = login_hint or account.email
        self._forget_old(access.user_id)
        state = token()
        pkce = new_pkce()
        self._pending[state] = _Pending(
            provider=provider,
            user_id=access.user_id,
            verifier=pkce.verifier,
            redirect_uri=redirect_uri,
            started=self._clock(),
            account_id=account_id,
        )
        self._sign_ins.started(access, provider, account)
        return authorize_url(client.app, redirect_uri, state, pkce, login_hint)

    async def finish(
        self, access: Access, provider: ProviderType, state: str, code: str
    ) -> Account:
        """The account the sign-in connected, or signed in again. Another
        user's sign-in answers as an unknown one and stays open for its
        owner."""
        with self._sign_ins.failing(access, provider):
            account, again = await self._finish(access, provider, state, code)
        self._sign_ins.finished(access, provider, account, again)
        return account

    async def _finish(
        self, access: Access, provider: ProviderType, state: str, code: str
    ) -> tuple[Account, bool]:
        """The account, and whether it signed in again."""
        pending = self._pending.get(state)
        if pending is None or pending.user_id != access.user_id:
            raise BadRequestError(UNKNOWN)
        del self._pending[state]
        if (
            pending.provider is not provider
            or self._clock() - pending.started > VALID_FOR
        ):
            raise BadRequestError(UNKNOWN)
        client = self._sign_ins.client(provider)
        tokens = await client.exchange(code, pending.redirect_uri, pending.verifier)
        return await self._sign_ins.connect(
            access, provider, tokens, pending.account_id
        )

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
        client = self._sign_ins.client(provider)
        account = self._sign_ins.checked(access, provider, account_id)
        self._forget_old(access.user_id)
        return await self._devices.start(access, provider, client, account_id, account)

    def device(
        self, access: Access, provider: ProviderType, sign_in_id: str
    ) -> DeviceSignIn:
        """A sign-in with a code this user started, as ``start_device``
        answered it."""
        return self._devices.shown(access, provider, sign_in_id)

    async def poll_device(
        self, access: Access, provider: ProviderType, sign_in_id: str
    ) -> Account | None:
        """The account once the person signed in with the code, None until
        then. A poll before the provider's interval has passed answers None
        without asking it. Another user's sign-in answers as an unknown
        one."""
        return await self._devices.poll(access, provider, sign_in_id)

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

    def in_browser(self, provider: ProviderType, redirect_uri: str) -> bool:
        """Whether a sign-in in the browser can come back to
        ``redirect_uri``. The project's app is sent back to localhost only."""
        client = self._clients.get(provider)
        if client is None:
            return False
        return not client.app.loopback_only or is_loopback(redirect_uri)

    def with_code(self, provider: ProviderType) -> bool:
        """Whether the provider offers a sign-in with a code on another
        device. Google does not for Gmail."""
        client = self._clients.get(provider)
        return client is not None and client.app.endpoints.device_url is not None

    def sign_in_hosts(self) -> list[str]:
        """The hosts a browser is sent to for a sign-in."""
        return sorted(
            {
                urlsplit(client.app.endpoints.authorize_url).netloc
                for client in self._clients.values()
            }
        )

    def _forget_old(self, user_id: str) -> None:
        """Drop expired sign-ins, and the oldest of this user's beyond the
        limit, each way."""
        now = self._clock()
        for state, pending in list(self._pending.items()):
            if now - pending.started > VALID_FOR:
                del self._pending[state]
        self._devices.forget_expired(now)
        forget_beyond(self._pending, user_id)
        self._devices.forget_beyond(user_id)
