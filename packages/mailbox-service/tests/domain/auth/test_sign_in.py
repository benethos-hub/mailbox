"""Signing in with a name and a password, and changing passwords
(CONCEPT 7.5)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import pytest

from benethos_mailbox_service.assembly import Services, build_services
from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.models import Grant, User
from benethos_mailbox_service.data.secrets import PasswordHasher, Scrypt
from benethos_mailbox_service.data.storage import (
    InMemoryPasswordRepository,
    InMemoryRoleRepository,
    InMemoryTokenRepository,
    InMemoryUserRepository,
)
from benethos_mailbox_service.domain.auth.passwords import Passwords
from benethos_mailbox_service.domain.auth.service import WRONG, AuthService
from benethos_mailbox_service.errors import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    RateLimitedError,
    SetupRequiredError,
    UnauthorizedError,
)

from ...conftest import ADMIN, CHEAP
from ...factor_helpers import credentials

SECRET = "correct horse battery staple"
OTHER = "a different long passphrase"
READER = Grant(accounts=["*"], allow=["mail.read"])


async def anna(services: Services, password: str = SECRET) -> User:
    """A user whose password an administrator set."""
    user = services.users.create_user(ADMIN, "Anna", [], [READER], ui_sign_in=True)
    await services.passwords.set_password(ADMIN, user.id, password)
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
    services.users.create_user(ADMIN, "Bot", [], [READER], ui_sign_in=True)
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
    stamp = await services.passwords.change_password(caller, SECRET, OTHER)
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
        await services.passwords.change_password(caller, current, new)


async def test_a_wrong_current_password_counts_as_a_failed_confirmation(
    services: Services,
) -> None:
    """It is audited and counts against the name, and a long one is
    refused before it is hashed."""
    user = await anna(services)
    signed = await services.auth.sign_in("Anna", SECRET, source="10.0.0.1")
    caller = services.auth.session_access(user.id, signed.stamp)
    for wrong in ["not the current one", "x" * 257] * 5:
        with pytest.raises(BadRequestError, match="current password is not right"):
            await services.passwords.change_password(caller, wrong, OTHER)
    assert credentials(services, "auth.confirm_failed")
    with pytest.raises(RateLimitedError):
        await services.passwords.change_password(caller, SECRET, OTHER)


async def test_a_password_is_not_the_name(services: Services) -> None:
    user = services.users.create_user(
        ADMIN, "a long user name here", [], [], ui_sign_in=True
    )
    with pytest.raises(BadRequestError, match="not be the user name"):
        await services.passwords.set_password(ADMIN, user.id, "A Long User Name Here")


async def test_setting_a_password_needs_the_right_and_the_rights(
    services: Services,
) -> None:
    user = await anna(services)
    helper = services.users.create_user(
        ADMIN,
        "Helper",
        [],
        [Grant(accounts=["acc_1"], allow=["mail.read"])],
        service=["users.manage"],
        ui_sign_in=True,
    )
    await services.passwords.set_password(ADMIN, helper.id, OTHER)
    signed = await services.auth.sign_in("Helper", OTHER, source="10.0.0.1")
    caller = services.auth.session_access(helper.id, signed.stamp)
    # Anna reads every account, more than the helper holds.
    with pytest.raises(ForbiddenError):
        await services.passwords.set_password(caller, user.id, "a password for anna")
    # Its own goes through change_password, with the current one.
    with pytest.raises(ConflictError, match="current one"):
        await services.passwords.set_password(
            caller, helper.id, "yet another passphrase"
        )


async def test_a_one_time_password_signs_in_once_and_is_noted(
    services: Services,
) -> None:
    user = services.users.create_user(ADMIN, "Anna", [], [READER], ui_sign_in=True)
    assert services.passwords.sign_in_state(user).last_sign_in_at is None
    password = await services.passwords.one_time_password(ADMIN, user.id)
    assert len(password) >= 24
    signed = await services.auth.sign_in("anna", password, source="10.0.0.1")
    assert signed.must_change is True and signed.previous is None
    assert services.passwords.sign_in_state(user).last_sign_in_at is not None
    again = await services.auth.sign_in("anna", password, source="10.0.0.1")
    assert again.previous is not None
    # Without users.manage no password for anyone, its own included.
    with pytest.raises(ForbiddenError):
        await services.passwords.one_time_password(
            services.auth.session_access(user.id, again.stamp), user.id
        )


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
    users.save(User(id="usr_a", name="anna", ui_sign_in=True))
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
    user = services.users.create_user(ADMIN, "Anna", [], [READER], ui_sign_in=True)
    older = Passwords(services.repositories.passwords, PasswordHasher(Scrypt(3, 1, 1)))
    before = await older.set(user.id, "Anna", SECRET, must_change=False)
    await services.auth.sign_in("Anna", SECRET, source="10.0.0.1")
    after = services.auth.passwords.stored(user.id)
    assert after is not None
    assert after.hash.startswith("scrypt$ln=4,") and before.hash.startswith(
        "scrypt$ln=3,"
    )
    # Nothing else changes: the session it came from stays valid.
    assert (after.must_change, after.updated_at) == (False, before.updated_at)


async def test_the_log_names_who_but_never_a_password(
    services: Services, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO):
        user = await anna(services)
        signed = await services.auth.sign_in("Anna", SECRET, source="10.0.0.1")
        caller = services.auth.session_access(user.id, signed.stamp)
        await services.passwords.change_password(caller, SECRET, OTHER)
        with pytest.raises(UnauthorizedError):
            await services.auth.sign_in(SECRET, SECRET, source="10.0.0.2")
    text = caplog.text
    assert f"set the password of Anna ({user.id})" in text
    assert f"Anna ({user.id}) signed in to the UI from 10.0.0.1" in text
    assert f"Anna ({user.id}) changed its password" in text
    # A password typed into the name field is not logged.
    assert "failed to sign in to the UI as an unknown name from 10.0.0.2" in text
    assert SECRET not in text and OTHER not in text


async def test_an_api_user_takes_no_password(services: Services) -> None:
    bot = services.users.create_user(ADMIN, "Bot", [], [READER])
    assert bot.ui_sign_in is False
    with pytest.raises(ConflictError, match="API user"):
        await services.passwords.set_password(ADMIN, bot.id, SECRET)
    with pytest.raises(ConflictError, match="API user"):
        await services.passwords.one_time_password(ADMIN, bot.id)


async def test_switching_the_ui_sign_in_off_ends_it(services: Services) -> None:
    user = await anna(services)
    signed = await services.auth.sign_in("Anna", SECRET, source="10.0.0.1")
    services.users.update_user(ADMIN, user.id, ui_sign_in=False)
    # The password is gone, the session ends, a sign-in answers as wrong.
    assert services.auth.passwords.stored(user.id) is None
    with pytest.raises(UnauthorizedError):
        services.auth.session_access(signed.user_id, signed.stamp)
    with pytest.raises(UnauthorizedError, match="wrong user name or password"):
        await services.auth.sign_in("Anna", SECRET, source="10.0.0.2")
    # Switched on again: a one-time password, to be changed first.
    services.users.update_user(ADMIN, user.id, ui_sign_in=True)
    password = await services.passwords.one_time_password(ADMIN, user.id)
    again = await services.auth.sign_in("Anna", password, source="10.0.0.3")
    assert again.must_change is True


async def test_nobody_takes_its_own_sign_in_or_disables_itself(
    services: Services,
) -> None:
    helper = services.users.create_user(
        ADMIN,
        "Helper",
        [],
        [],
        service=["users.manage"],
        ui_sign_in=True,
    )
    await services.passwords.set_password(ADMIN, helper.id, OTHER)
    signed = await services.auth.sign_in("Helper", OTHER, source="10.0.0.1")
    caller = services.auth.session_access(helper.id, signed.stamp)
    with pytest.raises(ConflictError, match="disable itself"):
        services.users.update_user(caller, helper.id, disabled=True)
    with pytest.raises(ConflictError, match="its own UI sign-in"):
        services.users.update_user(caller, helper.id, ui_sign_in=False)
    renamed = services.users.update_user(caller, helper.id, name="Helper2")
    assert renamed.ui_sign_in is True and not renamed.disabled


async def test_set_password_on_the_host_switches_the_ui_sign_in_on(
    services: Services,
) -> None:
    services.users.create_user(ADMIN, "Bot", [], [READER])
    user, password = await services.passwords.reset_password("bot")
    assert user.ui_sign_in is True
    signed = await services.auth.sign_in("Bot", password, source="10.0.0.1")
    assert signed.must_change is True


def test_the_hashes_at_once_come_from_the_settings() -> None:
    settings = Settings(storage="memory", password_hashes_at_once=3)
    services = build_services(settings, password_hasher=CHEAP)
    assert services.auth.passwords.at_once == 3
