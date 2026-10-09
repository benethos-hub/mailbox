"""The devices of the second factor: added, renamed and removed by their
owner, removed by an administrator or the host (docs/AUTHENTICATION.md
4)."""

from __future__ import annotations

import pytest

from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.data.secrets import totp
from benethos_mailbox_service.domain.auth.factors import (
    MAX_DEVICES,
    RECOVERY_CODES,
)
from benethos_mailbox_service.errors import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
)

from ...conftest import ADMIN
from ...factor_helpers import (
    SECRET,
    SOURCE,
    START,
    Clock,
    access_of,
    add_device,
    anna,
    clock,
    credentials,
    details,
    device_id,
    now_code,
    services,
    with_factor,
)

pytestmark = pytest.mark.usefixtures("master_key")
# The fixtures come from factor_helpers.
__all__ = ["clock", "services"]

# --- the first device -----------------------------------------------------------


async def test_adding_asks_for_the_password(services: Services) -> None:
    access = access_of(services, await anna(services))
    with pytest.raises(BadRequestError):
        await services.factors.begin(access, "Phone", "a wrong password, long enough")
    assert credentials(services, "auth.confirm_failed")


async def test_a_wrong_first_code_stores_nothing(
    services: Services, clock: Clock
) -> None:
    user = await anna(services)
    access = access_of(services, user)
    name, secret = await services.factors.begin(access, "Phone", SECRET)
    wrong = totp.code(secret, totp.step_of(clock()) + 5)
    with pytest.raises(BadRequestError):
        services.factors.confirm(access, name, secret, wrong)
    assert not services.factors.has(user.id)


async def test_the_first_device_turns_the_factor_on(
    services: Services, clock: Clock
) -> None:
    user, _, codes = await with_factor(services, clock)
    assert services.factors.has(user.id)
    assert len(codes) == RECOVERY_CODES == len(set(codes))
    state = services.factors.mine(access_of(services, user))
    assert [d.name for d in state.devices] == ["Phone"]
    assert state.devices[0].created_at == START
    assert state.recovery_codes_left == RECOVERY_CODES
    assert details(services, "users.device_added") == [
        "added the device Phone to its second factor, which turns it on"
    ]


async def test_the_secret_is_stored_sealed(services: Services, clock: Clock) -> None:
    user, secret, _ = await with_factor(services, clock)
    [stored] = services.repositories.factors.devices(user.id)
    assert totp.base32(secret).encode() not in stored.secret.ciphertext


@pytest.mark.parametrize("name", ["", "   ", "x" * 61])
async def test_a_device_needs_a_fitting_name(services: Services, name: str) -> None:
    access = access_of(services, await anna(services))
    with pytest.raises(BadRequestError):
        await services.factors.begin(access, name, SECRET)


async def test_spaces_in_a_name_are_made_one(services: Services) -> None:
    access = access_of(services, await anna(services))
    name, _ = await services.factors.begin(access, "  Old \n phone ", SECRET)
    assert name == "Old phone"


# --- further devices ------------------------------------------------------------


async def test_a_further_device_needs_a_code(services: Services, clock: Clock) -> None:
    user, secret, _ = await with_factor(services, clock)
    access = access_of(services, user)
    with pytest.raises(BadRequestError, match="code"):
        await services.factors.begin(access, "Tablet", SECRET)
    with pytest.raises(BadRequestError, match="code"):
        await services.factors.begin(access, "Tablet", SECRET, "000000")
    second, codes = await add_device(
        services, user, clock, "Tablet", now_code(secret, clock)
    )
    # The recovery codes stay one set: a further device brings none.
    assert codes == []
    assert services.factors.mine(access).recovery_codes_left == RECOVERY_CODES
    assert second != secret
    assert details(services, "users.device_added")[0] == (
        "added the device Tablet to its second factor"
    )


async def test_a_recovery_code_adds_a_device_and_is_used_up(
    services: Services, clock: Clock
) -> None:
    user, _, codes = await with_factor(services, clock)
    await add_device(services, user, clock, "Tablet", codes[0])
    assert services.factors.mine(access_of(services, user)).recovery_codes_left == 9


async def test_a_code_of_any_device_signs_in(services: Services, clock: Clock) -> None:
    user, phone, _ = await with_factor(services, clock)
    tablet, _ = await add_device(
        services, user, clock, "Tablet", now_code(phone, clock)
    )
    clock.step()
    services.auth.sign_in_with_code(user.id, now_code(tablet, clock), source=SOURCE)
    # Each device keeps its own steps: the phone's code of this step works.
    services.auth.sign_in_with_code(user.id, now_code(phone, clock), source=SOURCE)
    # Both at the same time: in no certain order.
    assert sorted(details(services, "auth.signed_in")) == [
        "signed in to the UI with a code of Phone",
        "signed in to the UI with a code of Tablet",
    ]
    state = services.factors.mine(access_of(services, user))
    assert all(d.last_used_at == clock() for d in state.devices)


async def test_names_are_unique_whatever_the_case(
    services: Services, clock: Clock
) -> None:
    user, secret, _ = await with_factor(services, clock)
    with pytest.raises(ConflictError, match="named"):
        await services.factors.begin(
            access_of(services, user), "PHONE", SECRET, now_code(secret, clock)
        )


async def test_at_most_ten_devices(services: Services, clock: Clock) -> None:
    user, _, codes = await with_factor(services, clock)
    for number in range(2, MAX_DEVICES + 1):
        await add_device(services, user, clock, f"Device {number}", codes[number - 2])
    with pytest.raises(ConflictError, match="at most"):
        await services.factors.begin(
            access_of(services, user), "One too many", SECRET, codes[-1]
        )


async def test_adding_a_device_ends_the_sessions_before(
    services: Services, clock: Clock
) -> None:
    user, _, codes = await with_factor(services, clock)
    before = services.auth.sign_in_with_code(user.id, codes[0], source=SOURCE)
    access = access_of(services, user)
    name, tablet = await services.factors.begin(access, "Tablet", SECRET, codes[1])
    _, stamp = services.factors.confirm(access, name, tablet, now_code(tablet, clock))
    with pytest.raises(UnauthorizedError, match="second factor"):
        services.auth.session_access(user.id, before.stamp, factor=before.factor)
    # The session that added it carries on with the new stamp.
    services.auth.session_access(user.id, before.stamp, factor=stamp)


# --- renaming -------------------------------------------------------------------


async def test_a_device_is_renamed_and_sessions_stay(
    services: Services, clock: Clock
) -> None:
    user, _, codes = await with_factor(services, clock)
    signed = services.auth.sign_in_with_code(user.id, codes[0], source=SOURCE)
    access = access_of(services, user)
    services.factors.rename(access, device_id(services, user, "Phone"), "Old phone")
    assert [d.name for d in services.factors.mine(access).devices] == ["Old phone"]
    services.auth.session_access(user.id, signed.stamp, factor=signed.factor)
    assert details(services, "users.device_renamed") == [
        "renamed its device Phone to Old phone"
    ]


async def test_renaming_keeps_names_unique(services: Services, clock: Clock) -> None:
    user, _, codes = await with_factor(services, clock)
    await add_device(services, user, clock, "Tablet", codes[0])
    access = access_of(services, user)
    tablet = device_id(services, user, "Tablet")
    with pytest.raises(ConflictError):
        services.factors.rename(access, tablet, "phone")
    # Its own name in another case is no conflict.
    services.factors.rename(access, tablet, "TABLET")
    with pytest.raises(NotFoundError):
        services.factors.rename(access, "tfa_unknown", "Other")


# --- removing one's own ---------------------------------------------------------


async def test_the_owner_removes_a_device_with_password_and_code(
    services: Services, clock: Clock
) -> None:
    user, phone, codes = await with_factor(services, clock)
    await add_device(services, user, clock, "Tablet", codes[0])
    access = access_of(services, user)
    tablet = device_id(services, user, "Tablet")
    with pytest.raises(BadRequestError):
        await services.factors.remove_own(access, tablet, SECRET, "000000")
    with pytest.raises(BadRequestError):
        await services.factors.remove_own(
            access, tablet, "not the password at all", codes[1]
        )
    clock.step()
    stamp = await services.factors.remove_own(
        access, tablet, SECRET, now_code(phone, clock)
    )
    assert stamp is not None
    state = services.factors.mine(access)
    assert [d.name for d in state.devices] == ["Phone"]
    assert state.recovery_codes_left == 9
    assert details(services, "users.device_removed") == ["removed its device Tablet"]


async def test_the_last_device_removed_turns_the_factor_off(
    services: Services, clock: Clock
) -> None:
    user, _, codes = await with_factor(services, clock)
    access = access_of(services, user)
    stamp = await services.factors.remove_own(
        access, device_id(services, user, "Phone"), SECRET, codes[0]
    )
    assert stamp is None
    assert not services.factors.has(user.id)
    assert services.factors.mine(access).recovery_codes_left == 0
    assert details(services, "users.device_removed") == [
        "removed its device Phone, the last one: the second factor is off"
    ]


async def test_removing_an_unknown_device_is_refused(
    services: Services, clock: Clock
) -> None:
    user, _, codes = await with_factor(services, clock)
    with pytest.raises(NotFoundError):
        await services.factors.remove_own(
            access_of(services, user), "tfa_unknown", SECRET, codes[0]
        )


# --- another's ------------------------------------------------------------------


async def test_an_administrator_sees_the_devices_never_a_secret(
    services: Services, clock: Clock
) -> None:
    user, secret, _ = await with_factor(services, clock)
    state = services.factors.of(ADMIN, user.id)
    assert [d.name for d in state.devices] == ["Phone"]
    assert totp.base32(secret) not in state.model_dump_json()
    nobody = services.users.create_user(ADMIN, "Nobody", [], [])
    with pytest.raises(ForbiddenError):
        services.factors.of(access_of(services, nobody), user.id)


async def test_an_administrator_removes_one_device(
    services: Services, clock: Clock
) -> None:
    user, _, codes = await with_factor(services, clock)
    await add_device(services, user, clock, "Tablet", codes[0])
    signed = services.auth.sign_in_with_code(user.id, codes[1], source=SOURCE)
    services.factors.remove_device(ADMIN, user.id, device_id(services, user, "Phone"))
    assert [d.name for d in services.factors.of(ADMIN, user.id).devices] == ["Tablet"]
    with pytest.raises(UnauthorizedError):
        services.auth.session_access(user.id, signed.stamp, factor=signed.factor)
    with pytest.raises(NotFoundError):
        services.factors.remove_device(ADMIN, user.id, "tfa_unknown")
    assert details(services, "users.device_removed")[0].startswith(
        "removed the device Phone of Anna"
    )


async def test_an_administrator_removes_every_device(
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
    with pytest.raises(ConflictError):
        services.factors.remove_device(access_of(services, boss), boss.id, "tfa_x")


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
    with pytest.raises(ForbiddenError):
        services.factors.remove_device(
            access_of(services, helper), user.id, device_id(services, user, "Phone")
        )
    assert services.factors.has(user.id)


async def test_the_host_removes_it_by_name(services: Services, clock: Clock) -> None:
    user, _, _ = await with_factor(services, clock)
    assert services.factors.reset(" anna ").id == user.id
    assert not services.factors.has(user.id)
    assert credentials(services, "users.factor_removed") == ["host"]
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
