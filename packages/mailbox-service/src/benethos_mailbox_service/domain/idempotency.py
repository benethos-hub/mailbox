"""Idempotency-Key (CONCEPT 6.4): a retried request returns the first
result instead of running again. What matters for sending, which cannot be
taken back.

A key counts per account and user for 24 hours: two users may send the
same key without meeting. The same key with a different request is a
conflict. Requests with the same key run one after the other, so a retry
that arrives while the first is still sending waits for its result. A
request that fails stores nothing: it may be tried again.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import TypeVar

from pydantic import BaseModel

from ..common.clock import utc_now
from ..data.storage import IdempotencyRepository, StoredResult
from ..errors import IdempotencyConflictError
from .locks import KeyedLocks

R = TypeVar("R", bound=BaseModel)

log = logging.getLogger(__name__)

KEEP = timedelta(hours=24)


class Idempotency:
    def __init__(
        self,
        store: IdempotencyRepository,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._store = store
        self._clock = clock
        self._locks: KeyedLocks[tuple[str, str, str]] = KeyedLocks()

    async def run(
        self,
        account_id: str,
        key: str | None,
        operation: str,
        request: BaseModel,
        action: Callable[[], Awaitable[R]],
        result_type: type[R],
        *,
        user_id: str,
    ) -> R:
        """``action``'s result, or the stored one for a key the same user
        sent before. Another user's result is never handed out."""
        if key is None:
            return await action()
        fingerprint = _fingerprint(operation, request)
        async with self._locks.get((account_id, user_id, key)):
            now = self._clock()
            self._store.purge(now - KEEP)
            stored = self._store.get(account_id, user_id, key)
            if stored is not None:
                if (stored.operation, stored.request_hash) != (operation, fingerprint):
                    raise IdempotencyConflictError(
                        "this Idempotency-Key was used with a different request"
                    )
                return result_type.model_validate_json(stored.result)
            result = await action()
            # Done, e.g. sent: the result goes to the caller even when it
            # cannot be stored, or the caller would take it for a failure.
            try:
                self._store.put(
                    account_id,
                    user_id,
                    key,
                    StoredResult(operation, fingerprint, result.model_dump_json(), now),
                )
            except Exception:
                log.exception("the result for an Idempotency-Key was not stored")
            return result


def _fingerprint(operation: str, request: BaseModel) -> str:
    canonical = json.dumps(
        {"operation": operation, "request": request.model_dump(mode="json")},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()
