"""Account records in SQLite."""

from __future__ import annotations

import json
import sqlite3

from ...models import Account, AccountStatus
from ..accounts import SettingsDict
from .database import Database
from .rows import SqliteRows


class SqliteAccountRepository:
    def __init__(self, db: Database) -> None:
        self._db = db
        self._rows = SqliteRows(db, "accounts", "account", _account)

    def list(self) -> list[Account]:
        return self._rows.list()

    def get(self, account_id: str) -> Account:
        return self._rows.get(account_id)

    def add(self, account: Account, settings: SettingsDict | None = None) -> None:
        self._db.execute(
            "INSERT INTO accounts"
            " (id, provider, email, display_name, status, settings)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                account.id,
                account.provider.value,
                account.email,
                account.display_name,
                account.status.value,
                json.dumps(settings or {}),
            ),
        )

    def settings(self, account_id: str) -> SettingsDict:
        result: SettingsDict = json.loads(self._rows.row(account_id)["settings"])
        return result

    def set_status(self, account_id: str, status: AccountStatus) -> None:
        self._db.must_change(
            "UPDATE accounts SET status = ? WHERE id = ?",
            (status.value, account_id),
            "account",
            account_id,
        )

    def update(self, account: Account, settings: SettingsDict) -> None:
        self._db.must_change(
            "UPDATE accounts SET display_name = ?, settings = ? WHERE id = ?",
            (account.display_name, json.dumps(settings), account.id),
            "account",
            account.id,
        )

    def delete(self, account_id: str) -> None:
        self._rows.delete(account_id)


def _account(row: sqlite3.Row) -> Account:
    return Account(
        id=row["id"],
        provider=row["provider"],
        email=row["email"],
        display_name=row["display_name"],
        status=row["status"],
    )
