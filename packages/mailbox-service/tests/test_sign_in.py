"""Signing in with a name and a password, and changing passwords
(CONCEPT 7.5)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import SecretStr

from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.models import Grant, User
from benethos_mailbox_service.data.secrets import PasswordHasher, Scrypt
from benethos_mailbox_service.data.storage import (
    InMemoryPasswordRepository,
    InMemoryRoleRepository,
    InMemoryTokenRepository,
    InMemoryUserRepository,
)
from benethos_mailbox_service.domain.auth import WRONG, AuthService
from benethos_mailbox_service.domain.passwords import Passwords
from benethos_mailbox_service.errors import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    RateLimitedError,
    SetupRequiredError,
    UnauthorizedError,
)
from benethos_mailbox_service.main import Services, build_services

from .conftest import ADMIN

CHEAP = PasswordHasher(Scrypt(log_n=4, r=1, p=1))
SECRET = "correct horse battery staple"
OTHER = "a different long passphrase"
READER = Grant(accounts=["*"], allow=["mail.read"])


@pytest.fixture
def services() -> Services:
    settings = Settings(storage="memory", api_key=SecretStr("k"))
    return build_services(settings, password_hasher=CHEAP)


async def anna(services: Services, password: str = SECRET) -> User:
    """A user whose password an administrator set."""
    user = services.users.create_user(ADMIN, "Anna", [], [READER])
    await services.users.set_password(ADMIN, user.id, password)
    return user


async def test_the_right_password_signs_in(services: Services) -> None:
    user = await anna(services)
    signed = await services.auth.sign_in("Anna", SECRET, source="10.0.0.1")
    assert signed.user_id == user.id
    # Set by someone else: it must be changed first.
    assert signed.must_change is True
    access = services.auth.session_access(signed.user_id, signed.stamp)
    assert access.user_id == user.id and access.credential_id is None


async def test_the_name_ignores_case_and_blanks(services: Services) -> None:
    await anna(services)
    await services.auth.sign_in("  ANNA ", SECRET, source="10.0.0.1")


@pytest.mark.parametrize(
    ("name", "password"),
    [("Anna", "a wrong long passphrase"), ("Nobody", SECRET), ("", "")],
)
async def test_wrong_answers_alike(
    services: Services, name: str, password: str
) -> None:
    await anna(services)
    with pytest.raises(UnauthorizedError) as refused:
        await services.auth.sign_in(name, password, source="10.0.0.1")
    assert refused.value.message == WRONG


async def test_a_disabled_user_answers_alike(services: Services) -> None:
    user = await anna(services)
    services.users.update_user(ADMIN, user.id, disabled=True)
    with pytest.raises(UnauthorizedError, match=WRONG):
        await services.auth.sign_in("Anna", SECRET, source="10.0.0.1")


async def test_a_user_without_a_password_cannot_sign_in(services: Services) -> None:
    services.users.create_user(ADMIN, "Bot", [], [READER])
    with pytest.raises(UnauthorizedError, match=WRONG):
        await services.auth.sign_in("Bot", "", source="10.0.0.1")


async def test_no_user_at_all_asks_for_the_setup(services: Services) -> None:
    with pytest.raises(SetupRequiredError, match="create-admin"):
        await services.auth.sign_in("admin", SECRET, source="10.0.0.1")


# --- sessions and changes --------------------------------------------------------


async def test_a_changed_password_ends_the_other_sessions(services: Services) -> None:
    user = await anna(services)
    first = await services.auth.sign_in("Anna", SECRET, source="10.0.0.1")
    caller = services.auth.session_access(user.id, first.stamp)
    stamp = await services.users.change_password(caller, SECRET, OTHER)
    with pytest.raises(UnauthorizedError, match="sign in again"):
        services.auth.session_access(user.id, first.stamp)
    # The session that changed it carries on with the new stamp.
    services.auth.session_access(user.id, stamp)
    again = await services.auth.sign_in("Anna", OTHER, source="10.0.0.1")
    assert again.must_change is False


async def test_a_session_ends_with_its_user(services: Services) -> None:
    user = await anna(services)
    signed = await services.auth.sign_in("Anna", SECRET, source="10.0.0.1")
    services.users.update_user(ADMIN, user.id, disabled=True)
    with pytest.raises(UnauthorizedError, match="disabled"):
        services.auth.session_access(user.id, signed.stamp)
    services.users.delete_user(ADMIN, user.id)
    with pytest.raises(UnauthorizedError, match="no longer exists"):
        services.auth.session_access(user.id, signed.stamp)
    assert services.auth.passwords.stored(user.id) is None


@pytest.mark.parametrize(
    ("current", "new", "message"),
    [
        ("not the current one", OTHER, "current password is not right"),
        (SECRET, "too short", "at least 15"),
        (SECRET, "x" * 257, "at most 256"),
        (SECRET, SECRET, "is the current one"),
    ],
)
async def test_the_rules_of_a_new_password(
    services: Services, current: str, new: str, message: str
) -> None:
    user = await anna(services)
    signed = await services.auth.sign_in("Anna", SECRET, source="10.0.0.1")
    caller = services.auth.session_access(user.id, signed.stamp)
    with pytest.raises(BadRequestError, match=message):
        await services.users.change_password(caller, current, new)


async def test_a_password_is_not_the_name(services: Services) -> None:
    user = services.users.create_user(ADMIN, "a long user name here", [], [])
    with pytest.raises(BadRequestError, match="not be the user name"):
        await services.users.set_password(ADMIN, user.id, "A Long User Name Here")


async def test_setting_a_password_needs_the_right_and_the_rights(
    services: Services,
) -> None:
    user = await anna(services)
    helper = services.users.create_user(
        ADMIN, "Helper", [], [Grant(accounts=["acc_1"], allow=["users.manage"])]
    )
    await services.users.set_password(ADMIN, helper.id, OTHER)
    signed = await services.auth.sign_in("Helper", OTHER, source="10.0.0.1")
    caller = services.auth.session_access(helper.id, signed.stamp)
    # Anna reads every account, more than the helper holds.
    with pytest.raises(ForbiddenError):
        await services.users.set_password(caller, user.id, "a password for anna")
    # Its own goes through change_password, with the current one.
    with pytest.raises(ConflictError, match="current one"):
        await services.users.set_password(caller, helper.id, "yet another passphrase")


async def test_names_are_unique_regardless_of_case(services: Services) -> None:
    user = await anna(services)
    with pytest.raises(ConflictError, match="Anna exists"):
        services.users.create_user(ADMIN, "anna", [], [])
    other = services.users.create_user(ADMIN, "Berta", [], [])
    with pytest.raises(ConflictError):
        services.users.update_user(ADMIN, other.id, name="ANNA")
    # Its own name, in another case, is no conflict.
    services.users.update_user(ADMIN, user.id, name="ANNA")


# --- guessing ------------------------------------------------------------------------


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


async def test_a_name_guessed_at_from_many_addresses_waits_a_minute() -> None:
    clock = Clock()
    users = InMemoryUserRepository()
    users.save(User(id="usr_a", name="anna"))
    passwords = Passwords(InMemoryPasswordRepository(), CHEAP, clock)
    await passwords.set("usr_a", "anna", SECRET, must_change=False)
    auth = AuthService(
        users,
        InMemoryRoleRepository(),
        InMemoryTokenRepository(),
        clock=clock,
        passwords=passwords,
    )
    for n in range(10):
        with pytest.raises(UnauthorizedError):
            await auth.sign_in("anna", "a wrong long passphrase", source=f"10.0.0.{n}")
    with pytest.raises(RateLimitedError):
        await auth.sign_in("anna", SECRET, source="10.0.1.1")
    clock.now += timedelta(minutes=1, seconds=1)
    await auth.sign_in("Anna", SECRET, source="10.0.1.1")


async def test_an_older_hash_is_made_anew_at_the_sign_in(services: Services) -> None:
    user = services.users.create_user(ADMIN, "Anna", [], [READER])
    older = Passwords(
        services.auth.passwords._repository, PasswordHasher(Scrypt(3, 1, 1))
    )
    before = await older.set(user.id, "Anna", SECRET, must_change=False)
    await services.auth.sign_in("Anna", SECRET, source="10.0.0.1")
    after = services.auth.passwords.stored(user.id)
    assert after is not None
    assert after.hash.startswith("scrypt$ln=4,") and before.hash.startswith(
        "scrypt$ln=3,"
    )
    # Nothing else changes: the session it came from stays valid.
    assert (after.must_change, after.updated_at) == (False, before.updated_at)
