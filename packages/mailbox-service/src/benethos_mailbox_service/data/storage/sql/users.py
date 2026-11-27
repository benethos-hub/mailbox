"""Users, roles and tokens in SQL."""

from __future__ import annotations

import json
import string
from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa

from benethos_mailbox_common.storage import dialect

from ....common.clock import iso, parse_iso
from ...models import ApiToken, Grant, Role, User
from .rows import SqlRows, changed, next_position
from .schema import roles, tokens, users

if TYPE_CHECKING:
    from .database import Database


class SqlUserRepository(SqlRows[User]):
    def __init__(self, db: Database) -> None:
        super().__init__(db, users, "user", _user, order=[users.c.position])

    def save(self, user: User) -> None:
        # A user saved again keeps its place.
        with self._db.connected() as conn:
            conn.execute(
                dialect.insert_or_update(
                    users,
                    ["id"],
                    [
                        "name",
                        "name_lower",
                        "roles",
                        "service",
                        "grants",
                        "disabled",
                        "ui_sign_in",
                    ],
                    conn.dialect,
                ).values(
                    id=user.id,
                    name=user.name,
                    name_lower=ascii_lower(user.name),
                    roles=json.dumps(user.roles),
                    service=json.dumps(user.service),
                    grants=_grants_json(user.grants),
                    disabled=int(user.disabled),
                    ui_sign_in=int(user.ui_sign_in),
                    position=next_position(users),
                )
            )

    def count(self) -> int:
        with self._db.connected() as conn:
            counted: int = conn.execute(
                sa.select(sa.func.count()).select_from(users)
            ).scalar_one()
            return counted


_ASCII_LOWER = str.maketrans(string.ascii_uppercase, string.ascii_lowercase)


def ascii_lower(name: str) -> str:
    """``name`` with the letters A to Z in lower case and every other
    character as it is, as ``lower()`` of SQLite folds it: the key that
    keeps two names apart in the unique index."""
    return name.translate(_ASCII_LOWER)


def _user(row: sa.RowMapping) -> User:
    return User(
        id=row["id"],
        name=row["name"],
        roles=json.loads(row["roles"]),
        service=json.loads(row["service"]),
        grants=_grants(row["grants"]),
        disabled=bool(row["disabled"]),
        ui_sign_in=bool(row["ui_sign_in"]),
    )


class SqlRoleRepository(SqlRows[Role]):
    def __init__(self, db: Database) -> None:
        super().__init__(db, roles, "role", _role, order=[roles.c.position])

    def save(self, role: Role) -> None:
        # A role saved again keeps its place.
        with self._db.connected() as conn:
            conn.execute(
                dialect.insert_or_update(
                    roles, ["id"], ["service", "grants"], conn.dialect
                ).values(
                    id=role.id,
                    service=json.dumps(role.service),
                    grants=_grants_json(role.grants),
                    position=next_position(roles),
                )
            )


def _role(row: sa.RowMapping) -> Role:
    return Role(
        id=row["id"],
        service=json.loads(row["service"]),
        grants=_grants(row["grants"]),
    )


class SqlTokenRepository:
    def __init__(self, db: Database) -> None:
        self._db = db
        self._rows = SqlRows(
            db, tokens, "token", _api_token, order=[tokens.c.created_at, tokens.c.id]
        )

    def list_for_user(self, user_id: str) -> list[ApiToken]:
        with self._db.connected() as conn:
            rows = conn.execute(
                sa.select(tokens)
                .where(tokens.c.user_id == user_id)
                .order_by(tokens.c.created_at, tokens.c.id)
            ).mappings()
            return [_api_token(row) for row in rows]

    def get(self, token_id: str) -> ApiToken:
        return self._rows.get(token_id)

    def find_by_hash(self, token_hash: str) -> ApiToken | None:
        with self._db.connected() as conn:
            row = (
                conn.execute(sa.select(tokens).where(tokens.c.token_hash == token_hash))
                .mappings()
                .first()
            )
        return None if row is None else _api_token(row)

    def save(self, token: ApiToken) -> None:
        # A token saved again keeps the time it was made.
        with self._db.connected() as conn:
            conn.execute(
                dialect.insert_or_update(
                    tokens,
                    ["id"],
                    [
                        "user_id",
                        "name",
                        "token_hash",
                        "expires_at",
                        "last_used_at",
                        "revoked_at",
                    ],
                    conn.dialect,
                ).values(
                    id=token.id,
                    user_id=token.user_id,
                    name=token.name,
                    token_hash=token.token_hash,
                    created_at=iso(token.created_at),
                    expires_at=iso(token.expires_at),
                    last_used_at=iso(token.last_used_at),
                    revoked_at=iso(token.revoked_at),
                )
            )

    def touch(self, token_id: str, when: datetime) -> None:
        changed(
            self._db,
            sa.update(tokens)
            .where(tokens.c.id == token_id)
            .values(last_used_at=iso(when)),
        )

    def delete_for_user(self, user_id: str) -> None:
        changed(self._db, sa.delete(tokens).where(tokens.c.user_id == user_id))


def _api_token(row: sa.RowMapping) -> ApiToken:
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
