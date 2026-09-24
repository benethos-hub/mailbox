"""Account records: which mailboxes are connected.

The repository holds records only. It connects nothing and decides nothing,
that belongs to the domain.
"""

from __future__ import annotations

from typing import Protocol

from ...errors import NotFoundError
from ..models import Account


class AccountRepository(Protocol):
    def list(self) -> list[Account]: ...

    def get(self, account_id: str) -> Account: ...

    def add(self, account: Account) -> None: ...

    def delete(self, account_id: str) -> None: ...


class InMemoryAccountRepository:
    """For tests and development. SQLite follows in phase 1."""

    def __init__(self) -> None:
        self._accounts: dict[str, Account] = {}

    def list(self) -> list[Account]:
        return list(self._accounts.values())

    def get(self, account_id: str) -> Account:
        try:
            return self._accounts[account_id]
        except KeyError:
            raise NotFoundError(f"account {account_id} not found") from None

    def add(self, account: Account) -> None:
        self._accounts[account.id] = account

    def delete(self, account_id: str) -> None:
        self.get(account_id)
        del self._accounts[account_id]
