"""Password hashes and where they are kept (CONCEPT 7.5)."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from benethos_mailbox_service.data.models import User
from benethos_mailbox_service.data.secrets import PasswordHasher, Scrypt
from benethos_mailbox_service.data.storage import (
    Database,
    InMemoryPasswordRepository,
    PasswordRepository,
    SqlitePasswordRepository,
    SqliteUserRepository,
    StoredPassword,
)
from benethos_mailbox_service.errors import ConflictError

# Cheap, so the tests run fast. The service uses Scrypt().
CHEAP = Scrypt(log_n=4, r=1, p=1)
NOW = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)


def test_a_hash_verifies_its_password_only() -> None:
    hasher = PasswordHasher(CHEAP)
    stored = hasher.hash("correct horse battery staple")
    assert stored.startswith("scrypt$ln=4,r=1,p=1$")
    assert "correct horse" not in stored
    assert hasher.verify("correct horse battery staple", stored)
    assert not hasher.verify("correct horse battery stapler", stored)
    # A salt of its own: the same password, another hash.
    assert hasher.hash("correct horse battery staple") != stored


def test_the_same_password_typed_another_way_matches() -> None:
    hasher = PasswordHasher(CHEAP)
    # U+212B ANGSTROM SIGN and U+00C5 are the same letter after NFKC.
    assert hasher.verify("Ångström-passphrase", hasher.hash("Ångström-passphrase"))


@pytest.mark.parametrize(
    "stored",
    [
        "",
        "plain",
        "bcrypt$ln=4,r=1,p=1$AAAA$AAAA",
        "scrypt$ln=4,r=1$AAAA$AAAA",
        "scrypt$ln=4,r=1,p=1$not base64!$AAAA",
        # Out of bounds: a broken row must not start a huge computation.
        "scrypt$ln=40,r=8,p=1$AAAA$AAAA",
    ],
)
def test_a_hash_it_cannot_read_verifies_nothing(stored: str) -> None:
    hasher = PasswordHasher(CHEAP)
    assert not hasher.verify("anything", stored)
    assert hasher.needs_rehash(stored)


def test_older_parameters_ask_for_a_new_hash() -> None:
    old = PasswordHasher(CHEAP).hash("correct horse battery staple")
    newer = PasswordHasher(Scrypt(log_n=5, r=1, p=1))
    assert newer.verify("correct horse battery staple", old)
    assert newer.needs_rehash(old)
    assert not newer.needs_rehash(newer.hash("x" * 15))


def test_checking_nobody_does_the_work_of_a_check() -> None:
    hasher = PasswordHasher(CHEAP)
    hasher.verify_nothing("anything")
    hasher.verify_nothing("anything else")


# --- storage --------------------------------------------------------------------------


@pytest.fixture(params=["memory", "sqlite"])
def store(
    request: pytest.FixtureRequest, tmp_path: Path
) -> Iterator[PasswordRepository]:
    if request.param == "memory":
        yield InMemoryPasswordRepository()
        return
    db = Database(tmp_path / "pw.db")
    SqliteUserRepository(db).save(User(id="usr_a", name="anna"))
    yield SqlitePasswordRepository(db)
    db.close()


def test_store_round_trip(store: PasswordRepository) -> None:
    assert store.get("usr_a") is None
    stored = StoredPassword("scrypt$x", must_change=True, updated_at=NOW)
    store.set("usr_a", stored)
    assert store.get("usr_a") == stored
    changed = StoredPassword("scrypt$y", must_change=False, updated_at=NOW)
    store.set("usr_a", changed)
    assert store.get("usr_a") == changed
    store.delete("usr_a")
    assert store.get("usr_a") is None


def test_a_password_goes_with_its_user(tmp_path: Path) -> None:
    db = Database(tmp_path / "pw.db")
    users = SqliteUserRepository(db)
    users.save(User(id="usr_a", name="anna"))
    passwords = SqlitePasswordRepository(db)
    passwords.set("usr_a", StoredPassword("scrypt$x", False, NOW))
    users.delete("usr_a")
    assert passwords.get("usr_a") is None
    db.close()


def test_names_are_unique_regardless_of_case(tmp_path: Path) -> None:
    db = Database(tmp_path / "pw.db")
    users = SqliteUserRepository(db)
    users.save(User(id="usr_a", name="Anna"))
    with pytest.raises(ConflictError):
        users.save(User(id="usr_b", name="anna"))
    db.close()


def test_the_migration_renames_a_name_taken_twice(tmp_path: Path) -> None:
    path = tmp_path / "old.db"
    Database(path).close()
    raw = sqlite3.connect(path)
    with raw:
        # Back to schema 8, with a name two users share.
        raw.execute("DROP INDEX users_name")
        raw.execute("DROP TABLE passwords")
        raw.execute("UPDATE meta SET value = '8' WHERE key = 'schema_version'")
        raw.execute("INSERT INTO users (id, name) VALUES ('usr_11111111aa', 'Anna')")
        raw.execute("INSERT INTO users (id, name) VALUES ('usr_22222222bb', 'anna')")
    raw.close()
    db = Database(path)
    names = sorted(u.name for u in SqliteUserRepository(db).list())
    assert names == ["Anna", "anna-22222222"]
    db.close()
