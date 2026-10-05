"""Schema 9: passwords, and user names that are unique regardless of case, the
name being what a person signs in with. A name taken twice before
gets part of its id, so the index can be made. lower() and NOCASE
fold ASCII letters alone: two names that differ in the case of
another letter, such as Ä and ä, both stay. The domain compares names
with casefold() and refuses such a second name since.
"""

from __future__ import annotations

import sqlite3

from ..migration import Migration


class V0009PasswordsUniqueNames(Migration):
    version = 9
    statements = (
        """
        UPDATE users SET name = name || '-' || substr(id, 5, 8)
            WHERE rowid NOT IN (SELECT MIN(rowid) FROM users GROUP BY lower(name))
        """,
        "CREATE UNIQUE INDEX users_name ON users (name COLLATE NOCASE)",
        """
        CREATE TABLE passwords (
            user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            hash TEXT NOT NULL,
            must_change INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        )
        """,
    )

    def before(self, db: sqlite3.Connection) -> list[str]:
        """The names the first statement is about to change, to be logged."""
        rows = db.execute(
            "SELECT id, name FROM users WHERE rowid NOT IN"
            " (SELECT MIN(rowid) FROM users GROUP BY lower(name))"
        ).fetchall()
        return [
            f"user {row['name']} renamed to {row['name']}-{row['id'][4:12]}: "
            "the name was taken regardless of case"
            for row in rows
        ]
