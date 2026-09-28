"""Results of requests sent with an ``Idempotency-Key`` (CONCEPT 6.4).

It only stores. The domain decides what a key means and how long it counts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from .table import drop_where


@dataclass(frozen=True)
class StoredResult:
    operation: str
    request_hash: str
    result: str  # JSON
    created_at: datetime


class IdempotencyRepository(Protocol):
    def get(self, account_id: str, user_id: str, key: str) -> StoredResult | None: ...

    def put(
        self, account_id: str, user_id: str, key: str, stored: StoredResult
    ) -> None: ...

    def purge(self, before: datetime) -> None:
        """Forget every result created before ``before``."""
        ...

    def forget_account(self, account_id: str) -> None:
        """The account is gone, and so are its keys."""
        ...


class InMemoryIdempotencyRepository:
    def __init__(self) -> None:
        self._items: dict[tuple[str, str, str], StoredResult] = {}

    def get(self, account_id: str, user_id: str, key: str) -> StoredResult | None:
        return self._items.get((account_id, user_id, key))

    def put(
        self, account_id: str, user_id: str, key: str, stored: StoredResult
    ) -> None:
        self._items[(account_id, user_id, key)] = stored

    def purge(self, before: datetime) -> None:
        drop_where(self._items, lambda _, stored: stored.created_at < before)

    def forget_account(self, account_id: str) -> None:
        drop_where(self._items, lambda key, _: key[0] == account_id)
