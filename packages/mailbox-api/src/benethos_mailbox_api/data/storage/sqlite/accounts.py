"""Account records in SQLite."""

from __future__ import annotations

import json
import sqlite3

from ...models import Account, AccountStatus
from ..accounts import SettingsDict
from ..table import missing
from .database import Database


class SqliteAccountRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def list(self) -> list[Account]:
        return [
            _account(r) for r in self._db.query("SELECT * FROM accounts ORDER BY rowid")
        ]

    def get(self, account_id: str) -> Account:
        return _account(self._row(account_id))

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
        result: SettingsDict = json.loads(self._row(account_id)["settings"])
        return result

    def set_status(self, account_id: str, status: AccountStatus) -> None:
        changed = self._db.execute(
            "UPDATE accounts SET status = ? WHERE id = ?", (status.value, account_id)
        )
        if not changed:
            raise missing("account", account_id)

    def update(self, account: Account, settings: SettingsDict) -> None:
        changed = self._db.execute(
            "UPDATE accounts SET display_name = ?, settings = ? WHERE id = ?",
            (account.display_name, json.dumps(settings), account.id),
        )
        if not changed:
            raise missing("account", account.id)

    def delete(self, account_id: str) -> None:
        if not self._db.execute("DELETE FROM accounts WHERE id = ?", (account_id,)):
            raise missing("account", account_id)

    def _row(self, account_id: str) -> sqlite3.Row:
        row = self._db.one("SELECT * FROM accounts WHERE id = ?", (account_id,))
        if row is None:
            raise missing("account", account_id)
        return row


def _account(row: sqlite3.Row) -> Account:
    return Account(
        id=row["id"],
        provider=row["provider"],
        email=row["email"],
        display_name=row["display_name"],
        status=row["status"],
    )
