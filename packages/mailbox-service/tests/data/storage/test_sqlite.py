"""The SQLite schema and its migrations: the steps of each version, the
registry and the fingerprints of released migrations."""

from __future__ import annotations

import hashlib
import importlib
import inspect
import json
import pkgutil
import re
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from benethos_mailbox_service.cli import main
from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.storage import (
    Database,
    SqliteRecoveryCodeRepository,
    SqliteRoleRepository,
    SqliteUserRepository,
)
from benethos_mailbox_service.data.storage.sqlite import SCHEMA_VERSION
from benethos_mailbox_service.data.storage.sqlite.migrations import (
    MIGRATIONS,
    Migration,
    MigrationRegistry,
    versions,
)
from benethos_mailbox_service.domain.rights import Access
from benethos_mailbox_service.errors import StorageError


def test_webhooks_of_users_deleted_before_are_dropped(tmp_path: Path) -> None:
    path = tmp_path / "old.db"
    Database(path).close()
    raw = sqlite3.connect(path)
    with raw:
        raw.execute("ALTER TABLE users DROP COLUMN service")
        raw.execute("ALTER TABLE roles DROP COLUMN service")
        raw.execute("ALTER TABLE changes DROP COLUMN folder_id")
        raw.execute("DROP TABLE activity")
        raw.execute("DROP TABLE totp_devices")
        raw.execute("DROP TABLE recovery_codes")
        raw.execute(
            "INSERT INTO users (id, name, roles, grants)"
            " VALUES ('usr_1', 'u', '[]', '[]')"
        )
        raw.execute(
            "INSERT INTO keys (key_id, nonce, ciphertext) VALUES ('k1', x'00', x'00')"
        )
        for hook, user in (("whk_1", "usr_1"), ("whk_2", "usr_gone")):
            raw.execute(
                "INSERT INTO webhooks (id, user_id, url, events, created_at, key_id,"
                " nonce, ciphertext, cursor) VALUES (?, ?, 'https://h', '[]', '',"
                " 'k1', x'00', x'00', 0)",
                (hook, user),
            )
        raw.execute("UPDATE meta SET value = '12' WHERE key = 'schema_version'")
    raw.close()
    db = Database(path)
    assert [r[0] for r in db.query("SELECT id FROM webhooks")] == ["whk_1"]
    db.close()


def _at_schema_14(path: Path, users: dict[str, list[dict[str, object]]]) -> None:
    """A database of schema 14: rights of the service still in the grants.
    ``users``: a user's name to its grants. A role of each name as well."""
    Database(path).close()
    raw = sqlite3.connect(path)
    with raw:
        for number, (name, grants) in enumerate(users.items()):
            raw.execute(
                "INSERT INTO users (id, name, grants) VALUES (?, ?, ?)",
                (f"usr_{number}", name, json.dumps(grants)),
            )
            raw.execute(
                "INSERT INTO roles (id, grants) VALUES (?, ?)",
                (name, json.dumps(grants)),
            )
        raw.execute("ALTER TABLE changes DROP COLUMN folder_id")
        raw.execute("DROP TABLE activity")
        raw.execute("DROP TABLE totp_devices")
        raw.execute("DROP TABLE recovery_codes")
        raw.execute("UPDATE meta SET value = '14' WHERE key = 'schema_version'")
    raw.close()


def test_rights_of_the_service_leave_the_grants(tmp_path: Path) -> None:
    """PERMISSIONS.md 8.1: what a grant named of the service moves to the
    service list, and nobody loses a right."""
    path = tmp_path / "old.db"
    every = ["*"]
    limit = {"recipients": ["a@example.org"], "max_sends_per_day": 3}
    _at_schema_14(
        path,
        {
            "admin": [{"accounts": every, "allow": ["admin"]}],
            "deputy": [{"accounts": ["acc_1"], "allow": ["admin"], **limit}],
            "manager": [
                {"accounts": ["acc_1"], "allow": ["users.manage", "mail.read"]}
            ],
            "operator": [
                {"accounts": every, "allow": ["accounts.manage", "webhooks.manage"]},
                {"accounts": ["acc_2"], "allow": ["create_account", "list_webhooks"]},
            ],
            "reader": [{"accounts": every, "allow": ["mail.read"]}],
        },
    )
    db = Database(path)
    users = {u.name: u for u in SqliteUserRepository(db).list()}
    roles = {r.id: r for r in SqliteRoleRepository(db).list()}
    for name in users:
        assert (users[name].service, users[name].grants) == (
            roles[name].service,
            roles[name].grants,
        )
    assert users["admin"].service == ["admin"]
    assert users["admin"].grants == []
    deputy = users["deputy"]
    assert deputy.service == ["users.manage", "webhooks.manage"]
    assert len(deputy.grants) == 1
    assert deputy.grants[0].accounts == ["acc_1"]
    assert "send" in deputy.grants[0].allow and "mail.read" in deputy.grants[0].allow
    assert deputy.grants[0].recipients == ["a@example.org"]
    assert deputy.grants[0].max_sends_per_day == 3
    assert users["manager"].service == ["users.manage"]
    assert users["manager"].grants[0].allow == ["mail.read"]
    operator = users["operator"]
    # create_account on named accounts gave nothing: it is dropped.
    assert operator.service == ["accounts.connect", "webhooks.manage", "list_webhooks"]
    assert [g.allow for g in operator.grants] == [["accounts.manage"]]
    assert users["reader"].service == []
    assert users["reader"].grants[0].allow == ["mail.read"]
    assert db.migrated is not None
    assert "schema 15: user admin: admin moved" in "\n".join(db.migrated.notes)
    assert not any("reader" in note for note in db.migrated.notes)
    db.close()


def test_nobody_loses_a_right_by_the_move(tmp_path: Path) -> None:
    """The rights a grant gave before, by the catalogue of schema 14, are
    the rights the user has after the move."""
    path = tmp_path / "old.db"
    _at_schema_14(
        path,
        {
            "deputy": [{"accounts": ["acc_1"], "allow": ["admin"]}],
            "operator": [{"accounts": ["*"], "allow": ["accounts.manage"]}],
        },
    )
    db = Database(path)
    users = {u.name: u for u in SqliteUserRepository(db).list()}
    deputy = Access.for_user(users["deputy"], {})
    assert deputy.allows("delete_message_permanent", "acc_1")
    assert deputy.allows("create_user") and deputy.allows("create_webhook")
    assert not deputy.allows("get_message", "acc_2")
    assert not deputy.allows("create_account") and not deputy.is_admin()
    operator = Access.for_user(users["operator"], {})
    assert operator.allows("create_account") and operator.allows("discover_account")
    assert operator.allows("verify_account", "acc_9")
    db.close()


def test_recovery_codes_of_schema_18_are_deleted(tmp_path: Path) -> None:
    """Their plain SHA-256 hashes cannot become keyed ones: a user makes
    new codes (docs/AUTHENTICATION.md 6)."""
    path = tmp_path / "old.db"
    Database(path).close()
    raw = sqlite3.connect(path)
    with raw:
        raw.execute("DROP TABLE recovery_codes")
        for statement in MIGRATIONS.step(18).statements[2:]:
            raw.execute(statement)
        raw.execute(
            "INSERT INTO users (id, name, roles, grants)"
            " VALUES ('usr_1', 'u', '[]', '[]')"
        )
        raw.execute("INSERT INTO recovery_codes (user_id, hash) VALUES ('usr_1', 'h')")
        raw.execute("UPDATE meta SET value = '18' WHERE key = 'schema_version'")
    raw.close()
    db = Database(path)
    assert db.query("SELECT * FROM recovery_codes") == []
    columns = [r[1] for r in db.query("PRAGMA table_info(recovery_codes)")]
    assert columns == ["user_id", "key_id", "hash", "used_at"]
    codes = SqliteRecoveryCodeRepository(db)
    assert codes.left("usr_1") == 0
    assert codes.use("usr_1", "", "h", datetime.now(UTC)) is False
    db.close()


def test_a_newer_schema_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "new.db"
    Database(path).close()
    raw = sqlite3.connect(path)
    with raw:
        raw.execute("UPDATE meta SET value = '999' WHERE key = 'schema_version'")
    raw.close()
    with pytest.raises(StorageError, match="newer"):
        Database(path)


def test_the_cli_names_a_newer_schema(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("MAILBOX_SERVICE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MAILBOX_SERVICE_STORAGE", "sqlite")
    path = Settings().database_path
    Database(path).close()
    raw = sqlite3.connect(path)
    with raw:
        raw.execute("UPDATE meta SET value = '999' WHERE key = 'schema_version'")
    raw.close()
    assert main(["users", "set-password", "admin"]) == 1
    assert "database schema 999 is newer" in capsys.readouterr().err


def test_a_migration_runs_before_then_its_statements() -> None:
    class Step(Migration):
        version = 99
        statements = ("INSERT INTO log VALUES ('statement')",)

        def before(self, db: sqlite3.Connection) -> list[str]:
            db.execute("INSERT INTO log VALUES ('before')")
            return ["said so"]

    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE log (step TEXT)")
    assert Step().apply(db) == ["said so"]
    assert [row[0] for row in db.execute("SELECT step FROM log")] == [
        "before",
        "statement",
    ]
    # The fingerprint is the module's source, here this test module.
    source = inspect.getsource(sys.modules[__name__])
    assert Step.fingerprint() == hashlib.sha256(source.encode()).hexdigest()


class _One(Migration):
    version = 1
    statements = ("CREATE TABLE one (id INTEGER)",)


class _Two(Migration):
    version = 2
    statements = ("CREATE TABLE two (id INTEGER)",)

    def before(self, db: sqlite3.Connection) -> list[str]:
        return ["two is coming"]


def test_the_registry_knows_its_steps_and_the_version_they_reach() -> None:
    registry = MigrationRegistry(_One(), _Two())
    assert registry.schema_version == 2
    assert len(registry) == 2
    assert [step.version for step in registry] == [1, 2]
    assert isinstance(registry.step(2), _Two)
    assert [step.version for step in registry.pending(1)] == [2]
    assert registry.pending(2) == ()
    with pytest.raises(ValueError, match="no migration to schema 3"):
        registry.step(3)


def test_the_registry_refuses_a_gap_or_a_wrong_place() -> None:
    with pytest.raises(ValueError, match="_Two says version 2 but stands at 1"):
        MigrationRegistry(_Two(), _One())
    with pytest.raises(ValueError, match="_Two says version 2 but stands at 1"):
        MigrationRegistry(_Two())


def test_the_registry_runs_a_step_and_records_its_version() -> None:
    registry = MigrationRegistry(_One(), _Two())
    db = sqlite3.connect(":memory:")
    registry.prepare(db)
    assert registry.version_of(db) == 0
    assert registry.apply(db, registry.step(1)) == []
    assert registry.version_of(db) == 1
    assert registry.apply(db, registry.step(2)) == ["schema 2: two is coming"]
    assert registry.version_of(db) == 2
    assert db.execute("SELECT count(*) FROM two").fetchone()[0] == 0


def test_each_migration_step_is_one_statement() -> None:
    """Executed one by one: a second statement in a step would be cut off
    by sqlite3, one that ended early would be refused."""
    for number, migration in enumerate(MIGRATIONS, 1):
        for step in migration.statements:
            assert not sqlite3.complete_statement(step), (number, step)
            assert sqlite3.complete_statement(step + ";"), (number, step)


def test_each_migration_module_is_in_the_list_at_its_number() -> None:
    """A module left out of MIGRATIONS, or one at the wrong place, would
    change the schema a version stands for. The class says its version,
    and it is the number in the name of its module."""
    found = {
        module.name: importlib.import_module(f"{versions.__name__}.{module.name}")
        for module in pkgutil.iter_modules(versions.__path__)
    }
    numbers = []
    for name, module in found.items():
        named = re.fullmatch(r"v(\d{4})_\w+", name)
        assert named, f"{name} is not named vNNNN_<subject>"
        numbers.append(int(named[1]))
        migration = MIGRATIONS.step(numbers[-1])
        assert type(migration).__module__ == module.__name__, name
        assert migration.version == numbers[-1], name
        assert type(migration).__name__.startswith(f"V{numbers[-1]:04d}"), name
    assert sorted(numbers) == list(range(1, SCHEMA_VERSION + 1))


# What each migration of a release runs, as a hash: a database of that
# release has run it, so it is never changed. A release adds its own.
# The fingerprint covers the step's whole module, comments included.
RELEASED = {
    # 0.1.0
    1: "6ea8ac6ebf74df7e1e29aead2cfdfca2bf369ddef7deec29effc6f10f3975c94",
    2: "22a23f705f4d3bbd14e76b9ed79050b9a41e96f7b78e7a9dbfbc1d93e655c323",
    3: "72dd59eb4771097f370cc87404db40d6eb246d50fb7007714591d85d8ba0bf7f",
    4: "3a01a598fddfd80d9127407ee275cdceedb6cf085c52ca2fcec506fb0d7914cf",
    5: "6cfed31ca15f31302232151e3b852b5d0d41dce03996a9b443b30076a5411bf5",
    # 0.2.0
    6: "b4315a0864a2a007b3ea3c11a37bd2bdc704b2d40cdaaa0741691def36f8df37",
    7: "790836401a7e247542752d920ed47fec64409e91031aa98f0c6617f49691276c",
    8: "df52d1587a3143ca007c822e21ce39712764feb8edee92f41a11a4f6caed6c73",
    9: "04a4fb35e6ed0203681fc25ad1dbaf7e862a181e96b6eee0800c31fd341879eb",
    10: "4baea0530d806e9f3790c5fa133562bf24f07f1d5a989d1f5f0193c2d31ff14d",
    11: "b2c91e737177cb76a533f4dc887a4693680bbc3dd29720f552883dc10793f4db",
    12: "e70816d3214e6bbd7999ab140e2f76315d9d7be6021e772e7c046918fd1e24b6",
    13: "421cb3d2c1160f80f725f8a5e7b257aeef151bf9b2dee31d0f9af07a852f9815",
    # 0.3.0
    14: "56b87a7bf8e46d262a5d12ff9ee705884a7d617e2b8bbe5503cd37fb5a052ac9",
    15: "e9cabbbe617caa9b981b0a05ec57c9e23417be65beb9860fe8be9980d717a1b2",
    16: "a8f3d386a6e41430c6c47beb0a0a9381633fc7cc32b1f3ec7902012d9dac353e",
    17: "bb72d83529bc4279e4531b1ea4145d9a0c20367d46ae05115a5450769c42e068",
    # 0.4.0
    18: "57c75f165c8205221073fe17a5297fafbf3f6cfb7641e78469e092dd60785dc4",
    19: "b1d0ba1464b42fc67fb4d2f4ff2ca4f038b8010a28c98a47b0fe1c4249759cca",
}


def fingerprint(number: int) -> str:
    return MIGRATIONS.step(number).fingerprint()


@pytest.mark.parametrize("number", sorted(RELEASED))
def test_a_released_migration_is_never_changed(number: int) -> None:
    assert fingerprint(number) == RELEASED[number], (
        f"migration {number} shipped in a release: make a new one instead"
    )
