"""The sign-in with a code (RFC 8628): the person enters a code at the
provider, on any device, and a poll connects the account once they
signed in. It needs no address the provider sends a browser back to.

A code is valid as long as the provider says, within a limit, and the
provider is asked no more often than it allows. Reached through
``OAuthService``, which checks the caller first.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from ...common.secret import token
from ...data.models import Account, ProviderType
from ...data.providers import DeviceCode, OAuthClient, Waiting
from ...errors import BadRequestError, ProviderUnavailableError
from ..rights import Access
from .signin import UNKNOWN, SignIns, forget_beyond

# A code is valid as long as the provider says, but no longer than this.
DEVICE_VALID_FOR = timedelta(minutes=30)
# What a provider that asks to be asked less often adds to the interval.
SLOWER = timedelta(seconds=5)


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


class DeviceSignIns:
    """The sign-ins with a code that are open, per id."""

    def __init__(self, sign_ins: SignIns, clock: Callable[[], datetime]) -> None:
        self._sign_ins = sign_ins
        self._clock = clock
        self._devices: dict[str, _Device] = {}

    async def start(
        self,
        access: Access,
        provider: ProviderType,
        client: OAuthClient,
        account_id: str | None,
        account: Account | None,
    ) -> DeviceSignIn:
        """A code from the provider, for a caller already checked:
        ``account`` to sign in again, None to connect a new one."""
        code = await client.device_code()
        now = self._clock()
        interval = timedelta(seconds=code.interval)
        sign_in_id = token()
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
        self._sign_ins.started(access, provider, account)
        return shown

    def shown(
        self, access: Access, provider: ProviderType, sign_in_id: str
    ) -> DeviceSignIn:
        """A sign-in with a code this user started, as ``start`` answered
        it."""
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
            raise BadRequestError(UNKNOWN)
        return device

    async def poll(
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
        failed = self._sign_ins.failing(access, provider)
        try:
            with failed:
                answer = await self._sign_ins.client(provider).poll_device(
                    device.code.device_code
                )
                if isinstance(answer, Waiting):
                    if answer.slow_down:
                        device.interval += SLOWER
                    device.next_at = self._clock() + device.interval
                    return None
                account, again = await self._sign_ins.connect(
                    access, provider, answer, device.account_id
                )
        except ProviderUnavailableError:
            # The provider was not reached. The code still stands: ask
            # again, more slowly.
            device.interval += SLOWER
            device.next_at = self._clock() + device.interval
            raise
        except Exception:
            # Declined, expired, or the account refused: start again.
            self._devices.pop(sign_in_id, None)
            raise
        finally:
            device.asking = False
        device.done = account
        self._sign_ins.finished(access, provider, account, again)
        return account

    def forget_expired(self, now: datetime) -> None:
        for sign_in_id, device in list(self._devices.items()):
            if now > device.expires_at:
                del self._devices[sign_in_id]

    def forget_beyond(self, user_id: str) -> None:
        """The oldest of the user's beyond the limit."""
        forget_beyond(self._devices, user_id)
