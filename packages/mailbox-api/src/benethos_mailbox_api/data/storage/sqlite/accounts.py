"""Account records in SQLite."""

from __future__ import annotations

import json
import sqlite3

from ....errors import NotFoundError
from ...models import Account, AccountStatus
from ..accounts import SettingsDict
from .database import Database


class SqliteAccountRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def list(self) -> list[Account]:
        return [
            _account(r) for r in self._db.query("SELECT * FROM accounts ORDER BY rowid")
        ]

    def get(self, account_id: str) -> Account:
        rows = self._db.query("SELECT * FROM accounts WHERE id = ?", (account_id,))
        if not rows:
            raise NotFoundError(f"account {account_id} not found")
        return _account(rows[0])

    def add(self, account: Account, settings: SettingsDict | None = None) -> None:
        with self._db.transaction() as db:
            db.execute(
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
        rows = self._db.query(
            "SELECT settings FROM accounts WHERE id = ?", (account_id,)
        )
        if not rows:
            raise NotFoundError(f"account {account_id} not found")
        result: SettingsDict = json.loads(rows[0]["settings"])
        return result

    def set_status(self, account_id: str, status: AccountStatus) -> None:
        with self._db.transaction() as db:
            updated = db.execute(
                "UPDATE accounts SET status = ? WHERE id = ?",
                (status.value, account_id),
            ).rowcount
            if updated == 0:
                raise NotFoundError(f"account {account_id} not found")

    def update(self, account: Account, settings: SettingsDict) -> None:
        with self._db.transaction() as db:
            updated = db.execute(
                "UPDATE accounts SET display_name = ?, settings = ? WHERE id = ?",
                (account.display_name, json.dumps(settings), account.id),
            ).rowcount
            if updated == 0:
                raise NotFoundError(f"account {account.id} not found")

    def delete(self, account_id: str) -> None:
        with self._db.transaction() as db:
            if (
                db.execute("DELETE FROM accounts WHERE id = ?", (account_id,)).rowcount
                == 0
            ):
                raise NotFoundError(f"account {account_id} not found")


def _account(row: sqlite3.Row) -> Account:
    return Account(
        id=row["id"],
        provider=row["provider"],
        email=row["email"],
        display_name=row["display_name"],
        status=row["status"],
    )
