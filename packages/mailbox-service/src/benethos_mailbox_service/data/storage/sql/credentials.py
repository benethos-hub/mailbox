"""The wrapped data key and encrypted credentials in SQL."""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from benethos_mailbox_common.storage import dialect

from ....common.clock import iso, parse_iso, utc_now
from ..credentials import EncryptedCredential, WrappedKey
from .rows import changed
from .schema import credentials, keys, meta

if TYPE_CHECKING:
    from .database import Database

_ACTIVE = "active_key"
_c = credentials.c


class SqlKeyRepository:
    """The key added last is the active one, named in ``meta``."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def active(self) -> WrappedKey | None:
        with self._db.connected() as conn:
            row = (
                conn.execute(
                    sa.select(keys).join(
                        meta,
                        sa.and_(meta.c.key == _ACTIVE, keys.c.key_id == meta.c.value),
                    )
                )
                .mappings()
                .first()
            )
        if row is None:
            return None
        return WrappedKey(row["key_id"], bytes(row["nonce"]), bytes(row["ciphertext"]))

    def add(self, key: WrappedKey) -> None:
        with self._db.connected() as conn:
            conn.execute(
                sa.insert(keys).values(
                    key_id=key.key_id,
                    nonce=key.nonce,
                    ciphertext=key.ciphertext,
                    created_at=iso(utc_now()),
                )
            )
            conn.execute(
                dialect.insert_or_update(meta, ["key"], None, conn.dialect).values(
                    key=_ACTIVE, value=key.key_id
                )
            )


class SqlCredentialRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def put(self, credential: EncryptedCredential) -> None:
        with self._db.connected() as conn:
            conn.execute(
                dialect.insert_or_update(
                    credentials, ["account_id", "field"], None, conn.dialect
                ).values(
                    account_id=credential.account_id,
                    field=credential.field,
                    key_id=credential.key_id,
                    nonce=credential.nonce,
                    ciphertext=credential.ciphertext,
                    updated_at=iso(credential.updated_at),
                )
            )

    def get(self, account_id: str, field: str) -> EncryptedCredential | None:
        with self._db.connected() as conn:
            row = (
                conn.execute(
                    sa.select(credentials).where(
                        _c.account_id == account_id, _c.field == field
                    )
                )
                .mappings()
                .first()
            )
        return None if row is None else _credential(row)

    def list_for_account(self, account_id: str) -> list[EncryptedCredential]:
        with self._db.connected() as conn:
            rows = conn.execute(
                sa.select(credentials)
                .where(_c.account_id == account_id)
                .order_by(_c.field)
            ).mappings()
            return [_credential(row) for row in rows]

    def forget_account(self, account_id: str) -> None:
        changed(self._db, sa.delete(credentials).where(_c.account_id == account_id))


def _credential(row: sa.RowMapping) -> EncryptedCredential:
    return EncryptedCredential(
        account_id=row["account_id"],
        field=row["field"],
        key_id=row["key_id"],
        nonce=bytes(row["nonce"]),
        ciphertext=bytes(row["ciphertext"]),
        updated_at=parse_iso(row["updated_at"]),
    )
