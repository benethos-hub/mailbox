"""Idempotency-Key (CONCEPT 6.4): a retried request returns the first
result instead of running again. What matters for sending, which cannot be
taken back.

A key counts per account for 24 hours. The same key with a different
request is a conflict. Requests with the same key run one after the other,
so a retry that arrives while the first is still sending waits for its
result. A request that fails stores nothing: it may be tried again.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import weakref
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import TypeVar

from pydantic import BaseModel

from ..common.clock import utc_now
from ..data.storage import IdempotencyRepository, StoredResult
from ..errors import IdempotencyConflictError

R = TypeVar("R", bound=BaseModel)

KEEP = timedelta(hours=24)


class Idempotency:
    def __init__(
        self,
        store: IdempotencyRepository,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._store = store
        self._clock = clock
        self._locks: weakref.WeakValueDictionary[tuple[str, str], asyncio.Lock] = (
            weakref.WeakValueDictionary()
        )

    async def run(
        self,
        account_id: str,
        key: str | None,
        operation: str,
        request: BaseModel,
        action: Callable[[], Awaitable[R]],
        result_type: type[R],
    ) -> R:
        """``action``'s result, or the stored one for a key seen before."""
        if key is None:
            return await action()
        fingerprint = _fingerprint(operation, request)
        lock = self._locks.get((account_id, key))
        if lock is None:
            lock = asyncio.Lock()
            self._locks[(account_id, key)] = lock
        async with lock:
            now = self._clock()
            self._store.purge(now - KEEP)
            stored = self._store.get(account_id, key)
            if stored is not None:
                if (stored.operation, stored.request_hash) != (operation, fingerprint):
                    raise IdempotencyConflictError(
                        "this Idempotency-Key was used with a different request"
                    )
                return result_type.model_validate_json(stored.result)
            result = await action()
            self._store.put(
                account_id,
                key,
                StoredResult(operation, fingerprint, result.model_dump_json(), now),
            )
            return result


def _fingerprint(operation: str, request: BaseModel) -> str:
    canonical = json.dumps(
        {"operation": operation, "request": request.model_dump(mode="json")},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()
