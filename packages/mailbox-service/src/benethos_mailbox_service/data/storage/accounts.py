"""Account records: which mailboxes are connected.

The repository holds records only. It connects nothing and decides nothing,
that belongs to the domain.
"""

from __future__ import annotations

from typing import Protocol

from ..models import Account, AccountStatus
from .table import Table

SettingsDict = dict[str, str | int | bool]


class AccountRepository(Protocol):
    def list(self) -> list[Account]: ...

    def get(self, account_id: str) -> Account: ...

    def add(self, account: Account, settings: SettingsDict | None = None) -> None: ...

    def settings(self, account_id: str) -> SettingsDict:
        """The connection settings the account was created with."""
        ...

    def set_status(self, account_id: str, status: AccountStatus) -> None: ...

    def update(self, account: Account, settings: SettingsDict) -> None:
        """Replace the display name and the settings of an account."""
        ...

    def delete(self, account_id: str) -> None: ...


class InMemoryAccountRepository:
    """For tests and ``storage = memory``."""

    def __init__(self) -> None:
        self._accounts: Table[Account] = Table("account")
        self._settings: dict[str, SettingsDict] = {}

    def list(self) -> list[Account]:
        return self._accounts.list()

    def get(self, account_id: str) -> Account:
        return self._accounts.get(account_id)

    def add(self, account: Account, settings: SettingsDict | None = None) -> None:
        self._accounts.add(account.id, account)
        self._settings[account.id] = dict(settings or {})

    def settings(self, account_id: str) -> SettingsDict:
        self.get(account_id)
        return dict(self._settings[account_id])

    def set_status(self, account_id: str, status: AccountStatus) -> None:
        account = self.get(account_id)
        self._accounts.put(account_id, account.model_copy(update={"status": status}))

    def update(self, account: Account, settings: SettingsDict) -> None:
        current = self.get(account.id)
        self._accounts.put(
            account.id,
            current.model_copy(update={"display_name": account.display_name}),
        )
        self._settings[account.id] = dict(settings)

    def delete(self, account_id: str) -> None:
        self._accounts.delete(account_id)
        del self._settings[account_id]
