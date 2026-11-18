"""The own password changed with the current one and, for a user with a
second factor, a code of it or a passkey (docs/AUTHENTICATION.md 4).
The forced change after the sign-in asks for none: the step after the
password asked a moment before."""

from __future__ import annotations

import pytest

from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.errors import BadRequestError

from ...conftest import ADMIN
from ...passkey_fake import Authenticator
from ..factor_helpers import (
    SECRET,
    Clock,
    access_of,
    add_passkey,
    anna,
    clock,
    credentials,
    now_code,
    services,
    signed,
    with_factor,
)

__all__ = ["clock", "services"]

OTHER = "another passphrase for anna"


async def test_without_a_second_factor_the_password_alone_does(
    services: Services,
) -> None:
    user = await anna(services)
    access = access_of(services, user)
    assert services.passwords.needs_code(access) is False
    await services.passwords.change_password(access, SECRET, OTHER)
    assert await services.auth.passwords.matches(user.id, OTHER)


async def test_a_second_factor_asks_for_a_code(
    services: Services, clock: Clock
) -> None:
    user, secret, _ = await with_factor(services, clock)
    access = access_of(services, user)
    assert services.passwords.needs_code(access) is True
    for wrong in ["", "000000"]:
        with pytest.raises(BadRequestError, match="code is not right"):
            await services.passwords.change_password(access, SECRET, OTHER, wrong)
    assert await services.auth.passwords.matches(user.id, SECRET)
    assert credentials(services, "auth.confirm_failed")
    await services.passwords.change_password(
        access, SECRET, OTHER, now_code(secret, clock)
    )
    assert await services.auth.passwords.matches(user.id, OTHER)


async def test_a_passkey_stands_in_for_the_code(services: Services) -> None:
    user = await anna(services)
    laptop = Authenticator(origin="https://mail.example.org")
    await add_passkey(services, user, laptop, "Laptop")
    access = access_of(services, user)
    await services.passwords.change_password(
        access, SECRET, OTHER, answer=signed(services, user, laptop)
    )
    assert await services.auth.passwords.matches(user.id, OTHER)


async def test_a_refused_new_password_uses_up_no_recovery_code(
    services: Services, clock: Clock
) -> None:
    user, _, codes = await with_factor(services, clock)
    access = access_of(services, user)
    factors = services.auth.factors
    assert factors is not None
    left = factors.codes_left(user.id)
    with pytest.raises(BadRequestError):
        await services.passwords.change_password(access, SECRET, "short", codes[0])
    assert factors.codes_left(user.id) == left
    await services.passwords.change_password(access, SECRET, OTHER, codes[0])
    assert factors.codes_left(user.id) == left - 1


async def test_the_forced_change_asks_for_no_code(
    services: Services, clock: Clock
) -> None:
    user, _, _ = await with_factor(services, clock)
    given = "a passphrase set for anna"
    await services.passwords.set_password(ADMIN, user.id, given)
    access = access_of(services, user)
    assert services.passwords.needs_code(access) is False
    await services.passwords.change_password(access, given, OTHER)
    assert await services.auth.passwords.matches(user.id, OTHER)
    # Her own now, the next change asks for the code again.
    assert services.passwords.needs_code(access) is True
