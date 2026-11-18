"""What the tests of the pages of the second factor share: a user with
a device, its codes, and the code page sent as a browser sends it."""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.data.models import User
from benethos_mailbox_service.data.secrets import totp

from ...conftest import UI_PASSWORD


def code_after(secret: bytes, steps: int = 1) -> str:
    """A code of a step after the current one: the current one may be
    taken already, by the setup."""
    return totp.code(secret, totp.step_of(datetime.now(UTC)) + steps)


def user_named(services: Services, name: str) -> User:
    user = services.auth.user_named(name)
    assert user is not None
    return user


def with_factor(services: Services, name: str) -> tuple[bytes, list[str]]:
    """The user of this name adds the device Phone: its secret and the
    recovery codes."""
    access = services.auth.access_of(user_named(services, name).id)
    assert access is not None
    begun = asyncio.run(services.totp.begin(access, "Phone", UI_PASSWORD))
    kept, secret = begun.name, begun.secret
    codes = (
        services.totp.confirm(access, kept, secret, code_after(secret, 0))
    ).recovery_codes
    return secret, codes


def code_form(client: TestClient, code: str) -> str:
    """The code page sent as a browser sends it: where it leads."""
    page = client.get("/ui/login/code")
    nonce = re.search(r'name="nonce" value="([^"]+)"', page.text)
    assert nonce is not None
    answer = client.post(
        "/ui/login/code",
        data={"code": code, "nonce": nonce.group(1)},
        follow_redirects=False,
    )
    assert answer.status_code == 303
    return str(answer.headers["location"])
