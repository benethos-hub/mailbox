"""One lock per key."""

from __future__ import annotations

import gc

import anyio

from benethos_mailbox_service.common.locks import KeyedLocks


def test_one_key_one_lock_while_it_is_held() -> None:
    locks: KeyedLocks[str] = KeyedLocks()
    held = locks.get("a")
    assert locks.get("a") is held
    assert locks.get("b") is not held


def test_a_lock_nobody_holds_goes() -> None:
    locks: KeyedLocks[str] = KeyedLocks()
    locks.get("a")
    gc.collect()
    assert len(locks._locks) == 0


async def test_a_key_runs_one_at_a_time_others_alongside() -> None:
    locks: KeyedLocks[str] = KeyedLocks()
    inside: list[str] = []
    seen: list[list[str]] = []

    async def work(key: str) -> None:
        async with locks.get(key):
            inside.append(key)
            await anyio.sleep(0.01)
            seen.append(sorted(inside))
            inside.remove(key)

    async with anyio.create_task_group() as group:
        for key in ("a", "a", "b", "b"):
            group.start_soon(work, key)
    assert all(found.count("a") <= 1 and found.count("b") <= 1 for found in seen)
    assert ["a", "b"] in seen
