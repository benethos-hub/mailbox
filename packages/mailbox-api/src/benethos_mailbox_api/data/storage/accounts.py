"""Account records: which mailboxes are connected.

The repository holds records only. It connects nothing and decides nothing,
that belongs to the domain.
"""

from __future__ import annotations

from typing import Protocol

from ...errors import NotFoundError
from ..models import Account, AccountStatus

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
        self._accounts: dict[str, Account] = {}
        self._settings: dict[str, SettingsDict] = {}

    def list(self) -> list[Account]:
        return list(self._accounts.values())

    def get(self, account_id: str) -> Account:
        try:
            return self._accounts[account_id]
        except KeyError:
            raise NotFoundError(f"account {account_id} not found") from None

    def add(self, account: Account, settings: SettingsDict | None = None) -> None:
        self._accounts[account.id] = account
        self._settings[account.id] = dict(settings or {})

    def settings(self, account_id: str) -> SettingsDict:
        self.get(account_id)
        return dict(self._settings[account_id])

    def set_status(self, account_id: str, status: AccountStatus) -> None:
        account = self.get(account_id)
        self._accounts[account_id] = account.model_copy(update={"status": status})

    def update(self, account: Account, settings: SettingsDict) -> None:
        current = self.get(account.id)
        self._accounts[account.id] = current.model_copy(
            update={"display_name": account.display_name}
        )
        self._settings[account.id] = dict(settings)

    def delete(self, account_id: str) -> None:
        self.get(account_id)
        del self._accounts[account_id]
        del self._settings[account_id]
