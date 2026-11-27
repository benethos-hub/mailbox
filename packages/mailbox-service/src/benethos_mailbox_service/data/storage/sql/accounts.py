"""Account records in SQL."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import sqlalchemy as sa

from benethos_mailbox_common.storage import rows as table_rows

from ...models import Abilities, Account, AccountStatus
from ..accounts import SettingsDict
from .schema import accounts

if TYPE_CHECKING:
    from .database import Database


class SqlAccountRepository:
    def __init__(self, db: Database) -> None:
        self._db = db
        self._rows = table_rows.SqlRows(
            db, accounts, "account", _account, order=[accounts.c.position]
        )

    def list(self) -> list[Account]:
        return self._rows.list()

    def get(self, account_id: str) -> Account:
        return self._rows.get(account_id)

    def add(self, account: Account, settings: SettingsDict | None = None) -> None:
        table_rows.rows_changed(
            self._db,
            sa.insert(accounts).values(
                id=account.id,
                provider=account.provider.value,
                email=account.email,
                display_name=account.display_name,
                status=account.status.value,
                settings=json.dumps(settings or {}),
                position=table_rows.next_position(accounts),
            ),
        )

    def settings(self, account_id: str) -> SettingsDict:
        result: SettingsDict = json.loads(self._rows.row(account_id)["settings"])
        return result

    def set_status(self, account_id: str, status: AccountStatus) -> None:
        self._change(account_id, status=status.value)

    def abilities(self, account_id: str) -> Abilities | None:
        return _abilities(self._rows.row(account_id))

    def set_abilities(self, account_id: str, abilities: Abilities) -> None:
        self._change(account_id, abilities=abilities.model_dump_json())

    def update(self, account: Account, settings: SettingsDict) -> None:
        self._change(
            account.id, display_name=account.display_name, settings=json.dumps(settings)
        )

    def delete(self, account_id: str) -> None:
        self._rows.delete(account_id)

    def _change(self, account_id: str, **values: object) -> None:
        self._rows.must_change(
            sa.update(accounts).where(accounts.c.id == account_id).values(**values),
            account_id,
        )


def _account(row: sa.RowMapping) -> Account:
    found = _abilities(row) or Abilities()
    return Account(
        id=row["id"],
        provider=row["provider"],
        email=row["email"],
        display_name=row["display_name"],
        status=row["status"],
        capabilities=found.capabilities,
        marks=found.marks,
    )


def _abilities(row: sa.RowMapping) -> Abilities | None:
    stored = row["abilities"]
    return None if stored is None else Abilities.model_validate_json(stored)
