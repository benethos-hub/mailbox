"""The second factor at the sign-in: a code of a device or a recovery
code after the password, and recovery codes made anew
(docs/AUTHENTICATION.md 3, 5)."""

from __future__ import annotations

import pytest

from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.common.secret import digest
from benethos_mailbox_service.data.secrets import cipher
from benethos_mailbox_service.data.storage import InMemoryRecoveryCodeRepository
from benethos_mailbox_service.domain.auth import recovery
from benethos_mailbox_service.domain.auth.recovery import (
    HASH_LABEL,
    RECOVERY_CODES,
    RecoveryCodes,
    new_recovery_code,
    recovery_text,
)
from benethos_mailbox_service.errors import (
    BadRequestError,
    ConflictError,
    RateLimitedError,
    UnauthorizedError,
)

from ...conftest import ADMIN
from ...factor_helpers import (
    SECRET,
    SOURCE,
    Clock,
    access_of,
    anna,
    clock,
    credentials,
    now_code,
    services,
    with_factor,
)

pytestmark = pytest.mark.usefixtures("master_key")
# The fixtures come from factor_helpers.
__all__ = ["clock", "services"]

# --- recovery codes -------------------------------------------------------------


def test_a_recovery_code_is_three_groups_of_five() -> None:
    code = new_recovery_code()
    assert [len(group) for group in code.split("-")] == [5, 5, 5]
    assert new_recovery_code() != code


@pytest.mark.parametrize(
    "typed",
    [
        "abcde-fghjk-mnpqr",
        " ABCDE FGHJK MNPQR ",
        "ABCDEFGHJKMNPQR",
        "abcde-fghjk-mnpqr\n",
    ],
)
def test_case_spaces_and_dashes_do_not_count(typed: str) -> None:
    assert recovery_text(typed) == "ABCDEFGHJKMNPQR"


def test_letters_read_as_digits_are_taken_as_such() -> None:
    assert recovery_text("IL0OO-11111-22222") == recovery_text("11000-11111-22222")


@pytest.mark.parametrize(
    "typed", ["", "ABCDE", "ABCDE-FGHJK", "ABCDE-FGHJK-MNPQRX", "ABCDE-FGHJK-MNPU1"]
)
def test_what_cannot_be_a_recovery_code_is_none(typed: str) -> None:
    assert recovery_text(typed) is None


def fixed_key(text: str) -> tuple[str, str]:
    return "key_1", cipher.keyed_hash(b"k" * 32, text.encode())


def test_a_recovery_code_counts_once_and_for_its_user_alone() -> None:
    codes = RecoveryCodes(InMemoryRecoveryCodeRepository(), fixed_key)
    made = codes.make("usr_a")
    assert len(made) == RECOVERY_CODES and codes.left("usr_a") == RECOVERY_CODES
    assert codes.use("usr_a", "00000-00000-00000") is False
    assert codes.use("usr_a", "not a code") is False
    # Another user with the same code has a hash of its own.
    assert codes.use("usr_b", made[0]) is False
    assert codes.use("usr_a", made[0]) is True
    assert codes.use("usr_a", made[0]) is False
    assert codes.left("usr_a") == RECOVERY_CODES - 1


def test_a_recovery_code_needs_the_key_it_was_hashed_with() -> None:
    repository = InMemoryRecoveryCodeRepository()
    made = RecoveryCodes(repository, fixed_key).make("usr_a")

    def other_key(text: str) -> tuple[str, str]:
        return "key_1", cipher.keyed_hash(b"o" * 32, text.encode())

    assert RecoveryCodes(repository, other_key).use("usr_a", made[0]) is False


async def test_recovery_codes_are_stored_keyed_and_bound_to_the_user(
    services: Services, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same code of two users hashes apart, and never as plain SHA-256:
    without the master key a stolen database allows no guess."""
    monkeypatch.setattr(recovery, "new_recovery_code", lambda: "ABCDE-FGHJK-MNPQR")
    user, _, _ = await with_factor(services, clock)
    text = "ABCDEFGHJKMNPQR"
    stored = services.repositories.recovery_codes
    key_id, annas = services.vault.keyed_hash(HASH_LABEL, f"{user.id}:{text}")
    _, berts = services.vault.keyed_hash(HASH_LABEL, f"usr_bert:{text}")
    assert not stored.use(user.id, key_id, digest(text), clock())
    assert not stored.use(user.id, key_id, berts, clock())
    assert stored.use(user.id, key_id, annas, clock())


async def test_a_recovery_code_of_digits_alone_signs_in(
    services: Services, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Digits go to the authenticator app first, then to the recovery codes."""
    monkeypatch.setattr(recovery, "new_recovery_code", lambda: "12345-67890-12345")
    user, _, codes = await with_factor(services, clock)
    assert codes[0] == "12345-67890-12345"
    signed = services.auth.sign_in_with_code(user.id, "123456789012345", source=SOURCE)
    assert signed.factor is not None
    assert credentials(services, "auth.signed_in") == ["password+recovery"]


# --- signing in -----------------------------------------------------------------


async def test_the_password_alone_does_not_sign_in(
    services: Services, clock: Clock
) -> None:
    user, _, _ = await with_factor(services, clock)
    signed = await services.auth.sign_in("Anna", SECRET, source=SOURCE)
    assert signed.needs_code
    assert services.auth.sign_in_state(user.id).last_sign_in_at is None
    assert not credentials(services, "auth.signed_in")


async def test_the_code_signs_in(services: Services, clock: Clock) -> None:
    user, secret, _ = await with_factor(services, clock)
    await services.auth.sign_in("Anna", SECRET, source=SOURCE)
    signed = services.auth.sign_in_with_code(
        user.id, now_code(secret, clock), source=SOURCE
    )
    assert not signed.needs_code and signed.factor is not None
    services.auth.session_access(user.id, signed.stamp, factor=signed.factor)
    assert credentials(services, "auth.signed_in") == ["password+totp"]
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
    assert credentials(services, "auth.code_failed")
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
    assert signed.factor is not None
    assert credentials(services, "auth.signed_in") == ["password+recovery"]
    assert credentials(services, "auth.recovery_code_used")
    assert services.factors.mine(access_of(services, user)).recovery_codes_left == 9
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
    fresh = await services.factors.renew_codes(access, SECRET, codes[1])
    assert services.factors.mine(access).recovery_codes_left == RECOVERY_CODES
    assert not set(fresh) & set(codes)
    with pytest.raises(UnauthorizedError):
        services.auth.sign_in_with_code(user.id, codes[2], source=SOURCE)
    assert credentials(services, "users.codes_renewed")


async def test_new_codes_need_password_and_code(
    services: Services, clock: Clock
) -> None:
    user, secret, codes = await with_factor(services, clock)
    access = access_of(services, user)
    with pytest.raises(BadRequestError, match="password"):
        await services.factors.renew_codes(access, "not it at all", codes[0])
    with pytest.raises(BadRequestError, match="code"):
        await services.factors.renew_codes(access, SECRET, "000000")
    # A code of the device does as well as a recovery code.
    await services.factors.renew_codes(access, SECRET, now_code(secret, clock))
    assert credentials(services, "auth.confirm_failed")


async def test_new_codes_need_a_factor(services: Services) -> None:
    access = access_of(services, await anna(services))
    with pytest.raises(ConflictError):
        await services.factors.renew_codes(access, SECRET, "123456")
