"""Users, roles and tokens in SQLite."""

from __future__ import annotations

import json
import sqlite3
import string
from datetime import datetime

from ....common.clock import iso, parse_iso
from ...models import ApiToken, Grant, Role, User
from .database import Database
from .rows import SqliteRows, next_position


class SqliteUserRepository(SqliteRows[User]):
    def __init__(self, db: Database) -> None:
        super().__init__(db, "users", "user", _user, order="position")

    def save(self, user: User) -> None:
        self._db.execute(
            "INSERT INTO users (id, name, name_lower, roles, service, grants,"
            " disabled, ui_sign_in, position) VALUES (?, ?, ?, ?, ?, ?, ?, ?,"
            f" {next_position('users')})"
            " ON CONFLICT(id) DO UPDATE SET name = excluded.name,"
            " name_lower = excluded.name_lower, roles = excluded.roles,"
            " service = excluded.service, grants = excluded.grants,"
            " disabled = excluded.disabled,"
            " ui_sign_in = excluded.ui_sign_in",
            (
                user.id,
                user.name,
                ascii_lower(user.name),
                json.dumps(user.roles),
                json.dumps(user.service),
                _grants_json(user.grants),
                int(user.disabled),
                int(user.ui_sign_in),
            ),
        )

    def count(self) -> int:
        return self._db.scalar("SELECT COUNT(*) FROM users")


_ASCII_LOWER = str.maketrans(string.ascii_uppercase, string.ascii_lowercase)


def ascii_lower(name: str) -> str:
    """``name`` with the letters A to Z in lower case and every other
    character as it is, as ``lower()`` of SQLite folds it: the key that
    keeps two names apart in the unique index."""
    return name.translate(_ASCII_LOWER)


def _user(row: sqlite3.Row) -> User:
    return User(
        id=row["id"],
        name=row["name"],
        roles=json.loads(row["roles"]),
        service=json.loads(row["service"]),
        grants=_grants(row["grants"]),
        disabled=bool(row["disabled"]),
        ui_sign_in=bool(row["ui_sign_in"]),
    )


class SqliteRoleRepository(SqliteRows[Role]):
    def __init__(self, db: Database) -> None:
        super().__init__(db, "roles", "role", _role, order="position")

    def save(self, role: Role) -> None:
        self._db.execute(
            "INSERT INTO roles (id, service, grants, position)"
            f" VALUES (?, ?, ?, {next_position('roles')})"
            " ON CONFLICT(id) DO UPDATE SET service = excluded.service,"
            " grants = excluded.grants",
            (role.id, json.dumps(role.service), _grants_json(role.grants)),
        )


def _role(row: sqlite3.Row) -> Role:
    return Role(
        id=row["id"],
        service=json.loads(row["service"]),
        grants=_grants(row["grants"]),
    )


class SqliteTokenRepository:
    def __init__(self, db: Database) -> None:
        self._db = db
        self._rows = SqliteRows(
            db, "tokens", "token", _api_token, order="created_at, id"
        )

    def list_for_user(self, user_id: str) -> list[ApiToken]:
        return self._db.query_as(
            _api_token,
            "SELECT * FROM tokens WHERE user_id = ? ORDER BY created_at, id",
            (user_id,),
        )

    def get(self, token_id: str) -> ApiToken:
        return self._rows.get(token_id)

    def find_by_hash(self, token_hash: str) -> ApiToken | None:
        return self._db.one_as(
            _api_token, "SELECT * FROM tokens WHERE token_hash = ?", (token_hash,)
        )

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

    def touch(self, token_id: str, when: datetime) -> None:
        self._db.execute(
            "UPDATE tokens SET last_used_at = ? WHERE id = ?", (iso(when), token_id)
        )

    def delete_for_user(self, user_id: str) -> None:
        self._db.execute("DELETE FROM tokens WHERE user_id = ?", (user_id,))


def _api_token(row: sqlite3.Row) -> ApiToken:
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
    return json.dumps([g.model_dump(mode="json") for g in grants])


def _grants(raw: str) -> list[Grant]:
    return [Grant.model_validate(g) for g in json.loads(raw)]
