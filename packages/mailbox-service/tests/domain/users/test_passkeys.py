"""Passkeys, the second method of the second factor: added, renamed and
removed by their owner, removed by an administrator, and signing in
after the password (docs/AUTHENTICATION.md 4, 5)."""

from __future__ import annotations

import pytest

from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.data.models import User
from benethos_mailbox_service.data.secrets import Party
from benethos_mailbox_service.domain.auth import MAX_DEVICES, Answer, SecondFactors
from benethos_mailbox_service.domain.auth.recovery import RECOVERY_CODES
from benethos_mailbox_service.errors import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
)

from ...conftest import ADMIN
from ...passkey_fake import Authenticator
from ..factor_helpers import (
    PARTY,
    SECRET,
    SOURCE,
    Clock,
    access_of,
    add_device,
    add_passkey,
    anna,
    clock,
    credentials,
    details,
    now_code,
    services,
    signed,
)

pytestmark = pytest.mark.usefixtures("master_key")
# The fixtures come from factor_helpers.
__all__ = ["clock", "services"]


def frame(services: Services) -> SecondFactors:
    assert services.auth.factors is not None
    return services.auth.factors


def passkey_id(services: Services, user: User, name: str) -> str:
    found = services.factors.mine(access_of(services, user)).passkeys
    return next(p.id for p in found if p.name == name)


async def with_passkey(services: Services) -> tuple[User, Authenticator]:
    """Anna with one passkey, Laptop."""
    user = await anna(services)
    laptop = Authenticator()
    await add_passkey(services, user, laptop, "Laptop")
    return user, laptop


# --- adding -----------------------------------------------------------------------


async def test_adding_asks_for_the_password(services: Services) -> None:
    access = access_of(services, await anna(services))
    with pytest.raises(BadRequestError):
        await services.passkeys.begin(access, "Laptop", "a wrong password!", PARTY)
    assert credentials(services, "auth.confirm_failed")


async def test_the_first_passkey_turns_the_factor_on(services: Services) -> None:
    user = await anna(services)
    codes = await add_passkey(services, user, Authenticator(), "Laptop")
    assert frame(services).has(user.id)
    assert len(codes) == RECOVERY_CODES
    state = services.factors.mine(access_of(services, user))
    assert [p.name for p in state.passkeys] == ["Laptop"]
    assert state.totp == []
    assert details(services, "users.passkey_added") == [
        "added the passkey Laptop to its second factor, which turns it on"
    ]


async def test_a_passkey_made_for_another_origin_is_refused(
    services: Services,
) -> None:
    user = await anna(services)
    access = access_of(services, user)
    begun = await services.passkeys.begin(access, "Laptop", SECRET, PARTY)
    options, challenge = begun.begun.options, begun.begun.challenge
    elsewhere = Authenticator(origin="https://evil.example")
    with pytest.raises(BadRequestError, match="not created"):
        services.passkeys.confirm(
            access, begun.name, Answer(PARTY, challenge, elsewhere.create(options))
        )
    # Asked under another party, the service's own host does not match.
    other = Party("evil.example", "https://evil.example")
    with pytest.raises(BadRequestError):
        services.passkeys.confirm(
            access, begun.name, Answer(other, challenge, elsewhere.create(options))
        )
    assert not frame(services).has(user.id)


async def test_a_further_device_needs_a_code_or_a_passkey(
    services: Services, clock: Clock
) -> None:
    user, laptop = await with_passkey(services)
    access = access_of(services, user)
    with pytest.raises(BadRequestError):
        await services.passkeys.begin(access, "Key", SECRET, PARTY, "123456")
    # Oldest first: the next one comes later.
    clock.tick(seconds=1)
    codes = await add_passkey(
        services, user, Authenticator(), "Key", answer=signed(services, user, laptop)
    )
    assert codes == []
    await add_device(
        services, user, clock, "Phone", answer=signed(services, user, laptop)
    )
    state = services.factors.mine(access)
    assert [p.name for p in state.passkeys] == ["Laptop", "Key"]
    assert [d.name for d in state.totp] == ["Phone"]


async def test_a_passkey_name_is_unique_and_the_number_limited(
    services: Services,
) -> None:
    user, laptop = await with_passkey(services)
    access = access_of(services, user)
    with pytest.raises(ConflictError, match="named"):
        await services.passkeys.begin(
            access, "LAPTOP", SECRET, PARTY, answer=signed(services, user, laptop)
        )
    for n in range(1, MAX_DEVICES):
        await add_passkey(
            services,
            user,
            Authenticator(),
            f"Key {n}",
            answer=signed(services, user, laptop),
        )
    with pytest.raises(ConflictError, match="at most"):
        await services.passkeys.begin(
            access, "One more", SECRET, PARTY, answer=signed(services, user, laptop)
        )


async def test_the_same_passkey_is_stored_once(services: Services) -> None:
    user, laptop = await with_passkey(services)
    with pytest.raises(ConflictError, match="stored already"):
        await add_passkey(
            services, user, laptop, "Again", answer=signed(services, user, laptop)
        )


# --- signing in ---------------------------------------------------------------------


async def test_a_passkey_signs_in_after_the_password(services: Services) -> None:
    user, laptop = await with_passkey(services)
    assert (await services.auth.sign_in("Anna", SECRET, source=SOURCE)).needs_code
    done = services.auth.sign_in_with_code(
        user.id, "", source=SOURCE, answer=signed(services, user, laptop)
    )
    assert done.factor == services.auth.factor_stamp(user.id)
    assert credentials(services, "auth.signed_in") == ["password+passkey"]
    assert details(services, "auth.signed_in") == [
        "signed in to the UI with the passkey Laptop"
    ]
    [passkey] = services.factors.mine(access_of(services, user)).passkeys
    assert passkey.last_used_at is not None


async def test_a_signature_signs_in_once(services: Services) -> None:
    user, laptop = await with_passkey(services)
    answer = signed(services, user, laptop)
    services.auth.sign_in_with_code(user.id, "", source=SOURCE, answer=answer)
    with pytest.raises(UnauthorizedError):
        services.auth.sign_in_with_code(user.id, "", source=SOURCE, answer=answer)
    assert len(details(services, "auth.code_failed")) == 1


async def test_a_copied_passkey_whose_counter_fell_is_refused(
    services: Services,
) -> None:
    user, laptop = await with_passkey(services)
    services.auth.sign_in_with_code(
        user.id, "", source=SOURCE, answer=signed(services, user, laptop)
    )
    laptop.counter = 0
    with pytest.raises(UnauthorizedError):
        services.auth.sign_in_with_code(
            user.id, "", source=SOURCE, answer=signed(services, user, laptop)
        )


async def test_a_synced_passkey_without_a_counter_signs_in_each_time(
    services: Services,
) -> None:
    user = await anna(services)
    phone = Authenticator(synced=True)
    await add_passkey(services, user, phone, "Phone")
    for _ in range(3):
        services.auth.sign_in_with_code(
            user.id, "", source=SOURCE, answer=signed(services, user, phone)
        )


async def test_another_users_passkey_does_not_sign_in(services: Services) -> None:
    user, _ = await with_passkey(services)
    other = services.users.create_user(ADMIN, "Ben", [], [], ui_sign_in=True)
    await services.auth.passwords.set(other.id, "Ben", SECRET, must_change=False)
    bens = Authenticator()
    await add_passkey(services, other, bens, "Bens laptop")
    begun = frame(services).challenge(user.id, PARTY)
    assert begun is not None
    answer = Answer(PARTY, begun.challenge, bens.get(begun.options))
    with pytest.raises(UnauthorizedError):
        services.auth.sign_in_with_code(user.id, "", source=SOURCE, answer=answer)


async def test_a_user_without_passkeys_has_no_challenge(
    services: Services, clock: Clock
) -> None:
    user = await anna(services)
    assert frame(services).challenge(user.id, PARTY) is None
    await add_device(services, user, clock, "Phone")
    assert frame(services).challenge(user.id, PARTY) is None


# --- renaming and removing ---------------------------------------------------------


async def test_a_passkey_is_renamed(services: Services) -> None:
    user, _ = await with_passkey(services)
    access = access_of(services, user)
    services.passkeys.rename(access, passkey_id(services, user, "Laptop"), "Work")
    assert [p.name for p in services.factors.mine(access).passkeys] == ["Work"]
    assert details(services, "users.passkey_renamed") == [
        "renamed its passkey Laptop to Work"
    ]
    with pytest.raises(NotFoundError):
        services.passkeys.rename(access, "psk_nothing", "Else")


async def test_the_last_passkey_removed_with_itself_turns_the_factor_off(
    services: Services,
) -> None:
    user, laptop = await with_passkey(services)
    stamp = await services.passkeys.remove_own(
        access_of(services, user),
        [passkey_id(services, user, "Laptop")],
        SECRET,
        answer=signed(services, user, laptop),
    )
    assert stamp is None
    assert not frame(services).has(user.id)
    assert frame(services).codes_left(user.id) == 0
    assert details(services, "users.passkey_removed") == [
        "removed its passkey Laptop, the last device: the second factor is off"
    ]


async def test_removing_needs_the_password_and_a_proof(services: Services) -> None:
    user, laptop = await with_passkey(services)
    access = access_of(services, user)
    target = [passkey_id(services, user, "Laptop")]
    with pytest.raises(BadRequestError):
        await services.passkeys.remove_own(access, target, SECRET, "000000")
    with pytest.raises(BadRequestError):
        await services.passkeys.remove_own(
            access, target, "wrong password!", answer=signed(services, user, laptop)
        )
    with pytest.raises(BadRequestError, match="tick"):
        await services.passkeys.remove_own(access, [], SECRET)
    assert frame(services).has(user.id)


async def test_a_totp_device_left_keeps_the_factor_on(
    services: Services, clock: Clock
) -> None:
    user = await anna(services)
    secret, _ = await add_device(services, user, clock, "Phone")
    clock.tick(seconds=30)
    laptop = Authenticator()
    await add_passkey(services, user, laptop, "Laptop", now_code(secret, clock))
    stamp = await services.passkeys.remove_own(
        access_of(services, user),
        [passkey_id(services, user, "Laptop")],
        SECRET,
        answer=signed(services, user, laptop),
    )
    assert stamp is not None
    assert frame(services).has(user.id)
    assert details(services, "users.passkey_removed") == ["removed its passkey Laptop"]


async def test_an_administrator_removes_a_passkey_of_another(
    services: Services,
) -> None:
    user, _ = await with_passkey(services)
    found = passkey_id(services, user, "Laptop")
    with pytest.raises(ConflictError):
        services.passkeys.remove_passkey(access_of(services, user), user.id, found)
    with pytest.raises(NotFoundError):
        services.passkeys.remove_passkey(ADMIN, user.id, "psk_nothing")
    services.passkeys.remove_passkey(ADMIN, user.id, found)
    assert not frame(services).has(user.id)
    assert details(services, "users.passkey_removed")[0].endswith(
        "the last device: the second factor is off"
    )


async def test_a_reader_removes_no_passkey(services: Services) -> None:
    user, _ = await with_passkey(services)
    reader = services.users.create_user(ADMIN, "Reader", [], [], ui_sign_in=True)
    with pytest.raises(ForbiddenError):
        services.passkeys.remove_passkey(
            access_of(services, reader), user.id, passkey_id(services, user, "Laptop")
        )


async def test_removing_the_whole_factor_takes_the_passkeys(
    services: Services,
) -> None:
    user, _ = await with_passkey(services)
    services.factors.remove(ADMIN, user.id)
    state = services.factors.of(ADMIN, user.id)
    assert (state.passkeys, state.recovery_codes_left) == ([], 0)
    assert not frame(services).has(user.id)


async def test_a_passkey_added_changes_the_stamp(services: Services) -> None:
    user, laptop = await with_passkey(services)
    before = services.auth.factor_stamp(user.id)
    await add_passkey(
        services, user, Authenticator(), "Key", answer=signed(services, user, laptop)
    )
    assert services.auth.factor_stamp(user.id) not in (None, before)


async def test_new_recovery_codes_with_a_passkey(services: Services) -> None:
    user, laptop = await with_passkey(services)
    access = access_of(services, user)
    with pytest.raises(BadRequestError):
        await services.factors.renew_codes(access, SECRET)
    codes = await services.factors.renew_codes(
        access, SECRET, answer=signed(services, user, laptop)
    )
    assert len(codes) == RECOVERY_CODES
