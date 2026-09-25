"""Users, roles and tokens in SQLite."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from ...models import ApiToken, Grant, Role, User
from ..table import missing
from .database import Database


class SqliteUserRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def list(self) -> list[User]:
        return [_user(r) for r in self._db.query("SELECT * FROM users ORDER BY rowid")]

    def get(self, user_id: str) -> User:
        row = self._db.one("SELECT * FROM users WHERE id = ?", (user_id,))
        if row is None:
            raise missing("user", user_id)
        return _user(row)

    def save(self, user: User) -> None:
        self._db.execute(
            "INSERT INTO users (id, name, roles, grants, disabled)"
            " VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT(id) DO UPDATE SET name = excluded.name,"
            " roles = excluded.roles, grants = excluded.grants,"
            " disabled = excluded.disabled",
            (
                user.id,
                user.name,
                json.dumps(user.roles),
                _grants_json(user.grants),
                int(user.disabled),
            ),
        )

    def delete(self, user_id: str) -> None:
        if not self._db.execute("DELETE FROM users WHERE id = ?", (user_id,)):
            raise missing("user", user_id)

    def count(self) -> int:
        return int(self._db.query("SELECT COUNT(*) FROM users")[0][0])


def _user(row: sqlite3.Row) -> User:
    return User(
        id=row["id"],
        name=row["name"],
        roles=json.loads(row["roles"]),
        grants=_grants(row["grants"]),
        disabled=bool(row["disabled"]),
    )


class SqliteRoleRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def list(self) -> list[Role]:
        return [_role(r) for r in self._db.query("SELECT * FROM roles ORDER BY rowid")]

    def get(self, role_id: str) -> Role:
        row = self._db.one("SELECT * FROM roles WHERE id = ?", (role_id,))
        if row is None:
            raise missing("role", role_id)
        return _role(row)

    def save(self, role: Role) -> None:
        self._db.execute(
            "INSERT INTO roles (id, grants) VALUES (?, ?)"
            " ON CONFLICT(id) DO UPDATE SET grants = excluded.grants",
            (role.id, _grants_json(role.grants)),
        )

    def delete(self, role_id: str) -> None:
        if not self._db.execute("DELETE FROM roles WHERE id = ?", (role_id,)):
            raise missing("role", role_id)


def _role(row: sqlite3.Row) -> Role:
    return Role(id=row["id"], grants=_grants(row["grants"]))


class SqliteTokenRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def list_for_user(self, user_id: str) -> list[ApiToken]:
        rows = self._db.query(
            "SELECT * FROM tokens WHERE user_id = ? ORDER BY rowid", (user_id,)
        )
        return [_token(r) for r in rows]

    def get(self, token_id: str) -> ApiToken:
        row = self._db.one("SELECT * FROM tokens WHERE id = ?", (token_id,))
        if row is None:
            raise missing("token", token_id)
        return _token(row)

    def find_by_hash(self, token_hash: str) -> ApiToken | None:
        row = self._db.one("SELECT * FROM tokens WHERE token_hash = ?", (token_hash,))
        return _token(row) if row is not None else None

    def save(self, token: ApiToken) -> None:
        self._db.execute(
            "INSERT INTO tokens (id, user_id, name, token_hash, created_at,"
            " expires_at, last_used_at, revoked_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(id) DO UPDATE SET name = excluded.name,"
            " expires_at = excluded.expires_at,"
            " last_used_at = excluded.last_used_at,"
            " revoked_at = excluded.revoked_at",
            (
                token.id,
                token.user_id,
                token.name,
                token.token_hash,
                _dt(token.created_at),
                _dt(token.expires_at),
                _dt(token.last_used_at),
                _dt(token.revoked_at),
            ),
        )

    def delete_for_user(self, user_id: str) -> None:
        self._db.execute("DELETE FROM tokens WHERE user_id = ?", (user_id,))


def _token(row: sqlite3.Row) -> ApiToken:
    return ApiToken(
        id=row["id"],
        user_id=row["user_id"],
        name=row["name"],
        token_hash=row["token_hash"],
        created_at=datetime.fromisoformat(row["created_at"]),
        expires_at=_parse_dt(row["expires_at"]),
        last_used_at=_parse_dt(row["last_used_at"]),
        revoked_at=_parse_dt(row["revoked_at"]),
    )


def _grants_json(grants: list[Grant]) -> str:
    return json.dumps([g.model_dump() for g in grants])


def _grants(raw: str) -> list[Grant]:
    return [Grant.model_validate(g) for g in json.loads(raw)]


def _dt(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _parse_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None
