"""The second factor: set up, the sign-in with a code, recovery codes, and
who removes one (docs/AUTHENTICATION.md)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest

from benethos_mailbox_service.assembly import Services, build_services
from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.models import ActivityFilter, Grant, User
from benethos_mailbox_service.data.secrets import totp
from benethos_mailbox_service.domain.auth.factors import (
    RECOVERY_CODES,
    new_recovery_code,
    recovery_hash,
)
from benethos_mailbox_service.domain.rights import Access
from benethos_mailbox_service.errors import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    RateLimitedError,
    UnauthorizedError,
)

from ...conftest import ADMIN, CHEAP

pytestmark = pytest.mark.usefixtures("master_key")

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
def services(clock: Clock) -> Iterator[Services]:
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


async def with_factor(
    services: Services, clock: Clock
) -> tuple[User, bytes, list[str]]:
    """Anna with a second factor: its secret and its recovery codes."""
    user = await anna(services)
    access = access_of(services, user)
    secret = await services.factors.begin(access, SECRET)
    codes, _ = services.factors.confirm(access, secret, now_code(secret, clock))
    # The code of setup is taken: the sign-in needs the next one.
    clock.step()
    return user, secret, codes


def activities(services: Services, name: str) -> list[str]:
    found = services.audit.list_activity(
        ADMIN, limit=100, matching=ActivityFilter(activity=name)
    )
    return [record.credential or "" for record in found.items]


# --- recovery codes -------------------------------------------------------------


def test_a_recovery_code_is_two_groups_of_five() -> None:
    code = new_recovery_code()
    first, second = code.split("-")
    assert len(first) == len(second) == 5
    assert new_recovery_code() != code


@pytest.mark.parametrize(
    "typed", ["abcde-fghjk", " ABCDE FGHJK ", "ABCDEFGHJK", "abcde-fghjk\n"]
)
def test_case_spaces_and_dashes_do_not_count(typed: str) -> None:
    assert recovery_hash(typed) == recovery_hash("ABCDE-FGHJK")


def test_letters_read_as_digits_are_taken_as_such() -> None:
    assert recovery_hash("IL0OO-11111") == recovery_hash("11000-11111")


@pytest.mark.parametrize("typed", ["", "ABCDE", "ABCDE-FGHJKX", "ABCDE-FGHU1"])
def test_what_cannot_be_a_recovery_code_has_no_hash(typed: str) -> None:
    assert recovery_hash(typed) is None


# --- setting up -----------------------------------------------------------------


async def test_setting_up_asks_for_the_password(services: Services) -> None:
    access = access_of(services, await anna(services))
    with pytest.raises(BadRequestError):
        await services.factors.begin(access, "a wrong password, long enough")
    assert activities(services, "auth.confirm_failed")


async def test_a_wrong_first_code_stores_nothing(
    services: Services, clock: Clock
) -> None:
    user = await anna(services)
    access = access_of(services, user)
    secret = await services.factors.begin(access, SECRET)
    wrong = totp.code(secret, totp.step_of(clock()) + 5)
    with pytest.raises(BadRequestError):
        services.factors.confirm(access, secret, wrong)
    assert not services.factors.has(user.id)


async def test_the_first_code_turns_the_factor_on(
    services: Services, clock: Clock
) -> None:
    user, _, codes = await with_factor(services, clock)
    assert services.factors.has(user.id)
    assert len(codes) == RECOVERY_CODES == len(set(codes))
    assert services.factors.codes_left(user.id) == RECOVERY_CODES
    assert services.auth.factor_stamp(user.id) == START
    assert activities(services, "users.factor_set_up")


async def test_the_secret_is_stored_sealed(services: Services, clock: Clock) -> None:
    user, secret, _ = await with_factor(services, clock)
    stored = services.repositories.factors.get(user.id)
    assert stored is not None
    assert totp.base32(secret).encode() not in stored.secret.ciphertext


async def test_a_second_factor_is_not_set_up_twice(
    services: Services, clock: Clock
) -> None:
    user, _, _ = await with_factor(services, clock)
    with pytest.raises(ConflictError):
        await services.factors.begin(access_of(services, user), SECRET)


async def test_setting_up_ends_the_sessions_before(
    services: Services, clock: Clock
) -> None:
    user = await anna(services)
    before = await services.auth.sign_in("Anna", SECRET, source=SOURCE)
    access = access_of(services, user)
    secret = await services.factors.begin(access, SECRET)
    _, stamp = services.factors.confirm(access, secret, now_code(secret, clock))
    with pytest.raises(UnauthorizedError, match="second factor"):
        services.auth.session_access(user.id, before.stamp)
    # The session that set it up carries on with the new stamp.
    services.auth.session_access(user.id, before.stamp, factor=stamp)


# --- signing in -----------------------------------------------------------------


async def test_the_password_alone_does_not_sign_in(
    services: Services, clock: Clock
) -> None:
    user, _, _ = await with_factor(services, clock)
    signed = await services.auth.sign_in("Anna", SECRET, source=SOURCE)
    assert signed.needs_code
    assert services.auth.sign_in_state(user.id).last_sign_in_at is None
    assert not activities(services, "auth.signed_in")


async def test_the_code_signs_in(services: Services, clock: Clock) -> None:
    user, secret, _ = await with_factor(services, clock)
    await services.auth.sign_in("Anna", SECRET, source=SOURCE)
    signed = services.auth.sign_in_with_code(
        user.id, now_code(secret, clock), source=SOURCE
    )
    assert not signed.needs_code and signed.factor == START
    services.auth.session_access(user.id, signed.stamp, factor=signed.factor)
    assert activities(services, "auth.signed_in") == ["password+totp"]
    assert services.auth.sign_in_state(user.id).last_sign_in_at == clock()


async def test_a_code_signs_in_once(services: Services, clock: Clock) -> None:
    user, secret, _ = await with_factor(services, clock)
    code = now_code(secret, clock)
    services.auth.sign_in_with_code(user.id, code, source=SOURCE)
    with pytest.raises(UnauthorizedError):
        services.auth.sign_in_with_code(user.id, code, source=SOURCE)


async def test_a_code_of_the_step_before_still_signs_in(
    services: Services, clock: Clock
) -> None:
    user, secret, _ = await with_factor(services, clock)
    late = now_code(secret, clock)
    clock.step()
    services.auth.sign_in_with_code(user.id, late, source=SOURCE)


async def test_a_wrong_code_counts_as_a_failed_sign_in(
    services: Services, clock: Clock
) -> None:
    user, _, _ = await with_factor(services, clock)
    with pytest.raises(UnauthorizedError):
        services.auth.sign_in_with_code(user.id, "000000", source=SOURCE)
    assert activities(services, "auth.code_failed")
    for _ in range(20):
        try:
            services.auth.sign_in_with_code(user.id, "000000", source=SOURCE)
        except UnauthorizedError:
            continue
        except RateLimitedError:
            break
    else:
        pytest.fail("wrong codes are never braked")


async def test_a_code_too_long_is_refused_unchecked(
    services: Services, clock: Clock
) -> None:
    user, _, _ = await with_factor(services, clock)
    with pytest.raises(UnauthorizedError):
        services.auth.sign_in_with_code(user.id, "1" * 41, source=SOURCE)


async def test_a_user_without_a_factor_has_no_code(services: Services) -> None:
    user = await anna(services)
    with pytest.raises(UnauthorizedError):
        services.auth.sign_in_with_code(user.id, "123456", source=SOURCE)


async def test_a_recovery_code_signs_in_once_and_is_told(
    services: Services, clock: Clock
) -> None:
    user, _, codes = await with_factor(services, clock)
    signed = services.auth.sign_in_with_code(user.id, codes[0].lower(), source=SOURCE)
    assert signed.factor == START
    assert activities(services, "auth.signed_in") == ["password+recovery"]
    assert activities(services, "auth.recovery_code_used")
    assert services.factors.codes_left(user.id) == RECOVERY_CODES - 1
    with pytest.raises(UnauthorizedError):
        services.auth.sign_in_with_code(user.id, codes[0], source=SOURCE)


async def test_a_disabled_user_does_not_get_past_the_code(
    services: Services, clock: Clock
) -> None:
    user, secret, _ = await with_factor(services, clock)
    services.users.update_user(ADMIN, user.id, disabled=True)
    with pytest.raises(UnauthorizedError):
        services.auth.sign_in_with_code(user.id, now_code(secret, clock), source=SOURCE)


# --- recovery codes anew --------------------------------------------------------


async def test_new_recovery_codes_replace_the_old(
    services: Services, clock: Clock
) -> None:
    user, _, codes = await with_factor(services, clock)
    access = access_of(services, user)
    services.auth.sign_in_with_code(user.id, codes[0], source=SOURCE)
    fresh = await services.factors.renew_codes(access, SECRET)
    assert services.factors.codes_left(user.id) == RECOVERY_CODES
    assert not set(fresh) & set(codes)
    with pytest.raises(UnauthorizedError):
        services.auth.sign_in_with_code(user.id, codes[1], source=SOURCE)
    assert activities(services, "users.codes_renewed")


async def test_new_codes_need_a_factor(services: Services) -> None:
    access = access_of(services, await anna(services))
    with pytest.raises(ConflictError):
        await services.factors.renew_codes(access, SECRET)


# --- removing -------------------------------------------------------------------


async def test_the_owner_removes_it_with_password_and_code(
    services: Services, clock: Clock
) -> None:
    user, secret, _ = await with_factor(services, clock)
    access = access_of(services, user)
    with pytest.raises(BadRequestError):
        await services.factors.remove_own(access, SECRET, "000000")
    assert services.factors.has(user.id)
    assert activities(services, "auth.confirm_failed")
    await services.factors.remove_own(access, SECRET, now_code(secret, clock))
    assert not services.factors.has(user.id)
    assert services.factors.codes_left(user.id) == 0
    assert activities(services, "users.factor_removed") == ["password"]


async def test_removing_needs_the_password_too(
    services: Services, clock: Clock
) -> None:
    user, secret, _ = await with_factor(services, clock)
    with pytest.raises(BadRequestError):
        await services.factors.remove_own(
            access_of(services, user),
            "not the password at all",
            now_code(secret, clock),
        )
    assert services.factors.has(user.id)


async def test_an_administrator_removes_it_and_ends_the_sessions(
    services: Services, clock: Clock
) -> None:
    user, secret, _ = await with_factor(services, clock)
    signed = services.auth.sign_in_with_code(
        user.id, now_code(secret, clock), source=SOURCE
    )
    services.factors.remove(ADMIN, user.id)
    assert not services.factors.has(user.id)
    with pytest.raises(UnauthorizedError):
        services.auth.session_access(user.id, signed.stamp, factor=signed.factor)
    with pytest.raises(NotFoundError):
        services.factors.remove(ADMIN, user.id)


async def test_nobody_removes_its_own_without_a_code(services: Services) -> None:
    boss = services.users.create_user(ADMIN, "Boss", [], [], service=["admin"])
    with pytest.raises(ConflictError):
        services.factors.remove(access_of(services, boss), boss.id)


async def test_removing_another_needs_its_rights(
    services: Services, clock: Clock
) -> None:
    user, _, _ = await with_factor(services, clock)
    helper = services.users.create_user(
        ADMIN, "Helper", [], [], service=["users.manage"]
    )
    # Anna reads mail, which Helper cannot hand out: no escalation.
    with pytest.raises(ForbiddenError):
        services.factors.remove(access_of(services, helper), user.id)
    assert services.factors.has(user.id)


async def test_the_host_removes_it_by_name(services: Services, clock: Clock) -> None:
    user, _, _ = await with_factor(services, clock)
    assert services.factors.reset(" anna ").id == user.id
    assert not services.factors.has(user.id)
    assert activities(services, "users.factor_removed") == ["host"]
    with pytest.raises(NotFoundError, match="no second factor"):
        services.factors.reset("Anna")
    with pytest.raises(NotFoundError, match="no user"):
        services.factors.reset("Nobody")


async def test_the_factor_goes_with_the_ui_sign_in(
    services: Services, clock: Clock
) -> None:
    user, _, _ = await with_factor(services, clock)
    services.users.update_user(ADMIN, user.id, ui_sign_in=False)
    assert not services.factors.has(user.id)


async def test_the_factor_goes_with_the_user(services: Services, clock: Clock) -> None:
    user, _, _ = await with_factor(services, clock)
    services.users.delete_user(ADMIN, user.id)
    assert not services.factors.has(user.id)


async def test_a_disabled_user_keeps_its_factor(
    services: Services, clock: Clock
) -> None:
    user, _, _ = await with_factor(services, clock)
    services.users.update_user(ADMIN, user.id, disabled=True)
    assert services.factors.has(user.id)


async def test_a_password_set_by_another_keeps_the_factor(
    services: Services, clock: Clock
) -> None:
    user, _, _ = await with_factor(services, clock)
    await services.passwords.one_time_password(ADMIN, user.id)
    assert services.factors.has(user.id)
