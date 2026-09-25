"""One lock per key, alive while someone holds or waits for it."""

from __future__ import annotations

import asyncio
import weakref
from collections.abc import Hashable
from typing import Generic, TypeVar

K = TypeVar("K", bound=Hashable)


class KeyedLocks(Generic[K]):
    """Locks by key that vanish with their last holder, so a service that
    serializes work per user, account or request key keeps no table that
    grows with every key it ever saw."""

    def __init__(self) -> None:
        self._locks: weakref.WeakValueDictionary[K, asyncio.Lock] = (
            weakref.WeakValueDictionary()
        )

    def get(self, key: K) -> asyncio.Lock:
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        return lock
