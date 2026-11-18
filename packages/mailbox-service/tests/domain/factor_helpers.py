"""What the tests of the second factor share: a user with a password,
and devices added the way the page adds them. The clock that steps and
the services on it are fixtures of conftest.py."""

from __future__ import annotations

from datetime import UTC, datetime

from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.data.models import ActivityFilter, Grant, User
from benethos_mailbox_service.data.secrets import Party, totp
from benethos_mailbox_service.domain.auth import Answer
from benethos_mailbox_service.domain.rights import Access

from ..clocks import Clock
from ..conftest import ADMIN
from ..passkey_fake import Authenticator

SECRET = "correct horse battery staple"
PARTY = Party("mail.example.org", "https://mail.example.org")
SOURCE = "10.0.0.1"
READER = Grant(accounts=["*"], allow=["mail.read"])
START = datetime(2026, 10, 9, 12, 0, 5, tzinfo=UTC)


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
    services: Services,
    user: User,
    clock: Clock,
    name: str,
    code: str = "",
    answer: Answer | None = None,
) -> tuple[bytes, list[str]]:
    """A device added the way the page does it: its secret, and the
    recovery codes it brought."""
    access = access_of(services, user)
    begun = await services.totp.begin(access, name, SECRET, code, answer)
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
    clock.tick(seconds=totp.STEP_SECONDS)
    return user, secret, codes


async def add_passkey(
    services: Services,
    user: User,
    device: Authenticator,
    name: str,
    code: str = "",
    answer: Answer | None = None,
) -> list[str]:
    """A passkey added the way the page does it: the recovery codes it
    brought."""
    access = access_of(services, user)
    begun = await services.passkeys.begin(access, name, SECRET, PARTY, code, answer)
    created = Answer(PARTY, begun.begun.challenge, device.create(begun.begun.options))
    return services.passkeys.confirm(access, begun.name, created).recovery_codes


def signed(services: Services, user: User, device: Authenticator) -> Answer:
    """The browser's answer to a challenge for the user's passkeys, signed
    by ``device``."""
    assert services.auth.factors is not None
    begun = services.auth.factors.challenge(user.id, PARTY)
    assert begun is not None
    return Answer(PARTY, begun.challenge, device.get(begun.options))


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
