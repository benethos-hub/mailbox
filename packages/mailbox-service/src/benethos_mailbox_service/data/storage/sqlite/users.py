"""Users, roles and tokens in SQLite."""

from __future__ import annotations

import json
import sqlite3

from ...models import ApiToken, Grant, Role, User
from ..table import missing
from .database import Database, iso, parse_iso
from .rows import SqliteRows


class SqliteUserRepository(SqliteRows[User]):
    def __init__(self, db: Database) -> None:
        super().__init__(db, "users", "user", _user)

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


class SqliteRoleRepository(SqliteRows[Role]):
    def __init__(self, db: Database) -> None:
        super().__init__(db, "roles", "role", _role)

    def save(self, role: Role) -> None:
        self._db.execute(
            "INSERT INTO roles (id, grants) VALUES (?, ?)"
            " ON CONFLICT(id) DO UPDATE SET grants = excluded.grants",
            (role.id, _grants_json(role.grants)),
        )


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
            " ON CONFLICT(id) DO UPDATE SET user_id = excluded.user_id,"
            " name = excluded.name, token_hash = excluded.token_hash,"
            " expires_at = excluded.expires_at,"
            " last_used_at = excluded.last_used_at,"
            " revoked_at = excluded.revoked_at",
            (
                token.id,
                token.user_id,
                token.name,
                token.token_hash,
                iso(token.created_at),
                iso(token.expires_at),
                iso(token.last_used_at),
                iso(token.revoked_at),
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
        created_at=parse_iso(row["created_at"]),
        expires_at=parse_iso(row["expires_at"]),
        last_used_at=parse_iso(row["last_used_at"]),
        revoked_at=parse_iso(row["revoked_at"]),
    )


def _grants_json(grants: list[Grant]) -> str:
    return json.dumps([g.model_dump() for g in grants])


def _grants(raw: str) -> list[Grant]:
    return [Grant.model_validate(g) for g in json.loads(raw)]
