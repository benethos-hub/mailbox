"""What the tests of the second factor share: a clock that steps, the
services on it, a user with a password, and devices added the way the
page adds them."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest

from benethos_mailbox_service.assembly import Services, build_services
from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.models import ActivityFilter, Grant, User
from benethos_mailbox_service.data.secrets import totp
from benethos_mailbox_service.domain.rights import Access

from .conftest import ADMIN, CHEAP

SECRET = "correct horse battery staple"
SOURCE = "10.0.0.1"
READER = Grant(accounts=["*"], allow=["mail.read"])
START = datetime(2026, 10, 9, 12, 0, 5, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> datetime:
        return self.now

    def step(self) -> None:
        self.now += timedelta(seconds=totp.STEP_SECONDS)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def services(master_key: None, clock: Clock) -> Iterator[Services]:
    built = build_services(
        Settings(storage="memory"), password_hasher=CHEAP, clock=clock
    )
    built.vault.initialize()
    yield built
    built.close()


async def anna(services: Services) -> User:
    """A user with a password of its own."""
    user = services.users.create_user(ADMIN, "Anna", [], [READER], ui_sign_in=True)
    await services.auth.passwords.set(user.id, "Anna", SECRET, must_change=False)
    return user


def access_of(services: Services, user: User) -> Access:
    access = services.auth.access_of(user.id)
    assert access is not None
    return access


def now_code(secret: bytes, clock: Clock) -> str:
    return totp.code(secret, totp.step_of(clock()))


async def add_device(
    services: Services, user: User, clock: Clock, name: str, code: str = ""
) -> tuple[bytes, list[str]]:
    """A device added the way the page does it: its secret, and the
    recovery codes it brought."""
    access = access_of(services, user)
    begun = await services.totp.begin(access, name, SECRET, code)
    kept, secret = begun.name, begun.secret
    codes = (
        services.totp.confirm(access, kept, secret, now_code(secret, clock))
    ).recovery_codes
    return secret, codes


async def with_factor(
    services: Services, clock: Clock
) -> tuple[User, bytes, list[str]]:
    """Anna with one device, Phone: its secret and the recovery codes."""
    user = await anna(services)
    secret, codes = await add_device(services, user, clock, "Phone")
    # The code of setup is taken: the sign-in needs the next one.
    clock.step()
    return user, secret, codes


def device_id(services: Services, user: User, name: str) -> str:
    devices = services.factors.mine(access_of(services, user)).totp
    return next(d.id for d in devices if d.name == name)


def credentials(services: Services, name: str) -> list[str]:
    found = services.audit.list_activity(
        ADMIN, limit=100, matching=ActivityFilter(activity=name)
    )
    return [record.credential or "" for record in found.items]


def details(services: Services, name: str) -> list[str]:
    """What the audit says of the activity, newest first."""
    found = services.audit.list_activity(
        ADMIN, limit=100, matching=ActivityFilter(activity=name)
    )
    return [record.detail for record in found.items]
