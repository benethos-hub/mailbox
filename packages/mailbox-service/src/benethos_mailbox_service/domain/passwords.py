"""Passwords of users: the rules they meet, and hashing that does not
hold up the service (CONCEPT 7.5).

A hash takes most of a second on purpose. It runs in a worker thread,
and only a few at once, so a flood of sign-ins cannot take every thread
or all the memory.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import TypeVar

import anyio

from ..common.clock import utc_now
from ..data.secrets import PasswordHasher
from ..data.storage import PasswordRepository, StoredPassword
from ..errors import BadRequestError

MIN_LENGTH = 15
MAX_LENGTH = 256
# Hashes running at once. Each takes 32 MiB with the default cost.
AT_ONCE = 2

T = TypeVar("T")


class Passwords:
    def __init__(
        self,
        repository: PasswordRepository,
        hasher: PasswordHasher | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._repository = repository
        self._hasher = hasher or PasswordHasher()
        self._clock = clock
        self._limiter = anyio.CapacityLimiter(AT_ONCE)

    def stored(self, user_id: str) -> StoredPassword | None:
        return self._repository.get(user_id)

    async def matches(self, user_id: str | None, password: str) -> bool:
        """Whether ``password`` is the user's. For a user that does not
        exist or has no password, the same work is done and False comes
        back, so the answer takes as long either way."""
        stored = self._repository.get(user_id) if user_id is not None else None
        if user_id is None or stored is None:
            await self._run(self._hasher.verify_nothing, password)
            return False
        matched = await self._run(self._hasher.verify, password, stored.hash)
        if matched and self._hasher.needs_rehash(stored.hash):
            # Made with older parameters: made anew, nothing else changes.
            fresh = await self._run(self._hasher.hash, password)
            self._repository.set(
                user_id, StoredPassword(fresh, stored.must_change, stored.updated_at)
            )
        return matched

    async def set(
        self, user_id: str, name: str, password: str, *, must_change: bool
    ) -> StoredPassword:
        """Checks the rules, then keeps the hash. The new time stamp ends
        the sessions signed in with the old password."""
        check(password, name)
        hashed = await self._run(self._hasher.hash, password)
        stored = StoredPassword(hashed, must_change, self._clock())
        self._repository.set(user_id, stored)
        return stored

    def delete(self, user_id: str) -> None:
        self._repository.delete(user_id)

    async def _run(self, function: Callable[..., T], *args: str) -> T:
        return await anyio.to_thread.run_sync(function, *args, limiter=self._limiter)


def check(password: str, name: str) -> None:
    """NIST SP 800-63B for a password that is the only factor: long, any
    characters, no rules on character classes, not the user's own name."""
    if len(password) < MIN_LENGTH:
        raise BadRequestError(f"a password needs at least {MIN_LENGTH} characters")
    if len(password) > MAX_LENGTH:
        raise BadRequestError(f"a password has at most {MAX_LENGTH} characters")
    if password.strip().casefold() == name.strip().casefold():
        raise BadRequestError("a password must not be the user name")
