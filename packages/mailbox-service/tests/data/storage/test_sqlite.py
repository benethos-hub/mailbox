"""The SQLite schema and its migrations: the steps of each version, the
registry and the fingerprints of released migrations."""

from __future__ import annotations

import hashlib
import importlib
import json
import pkgutil
import re
import sqlite3
from pathlib import Path

import pytest

from benethos_mailbox_service.cli import main
from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.storage import (
    Database,
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
    assert Step.fingerprint() == hashlib.sha256(Step.statements[0].encode()).hexdigest()


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
RELEASED = {
    # 0.1.0
    1: "e594d44acc853b6512efb56194296ce71115cacd449810f322e534b8c96894d6",
    2: "ff9d8f7ab7ee21a8e02a38482cd91fbbfe56ccc0978acb914a7a918ef886aa82",
    3: "fb834a11999de1b5ba3132b5bd5fec13738e274c25eff37f16a510cbf93dac08",
    4: "674023cf6bf2157755d570dd84051c99bd77bac24894dd37150bb3ae2bfe69d0",
    5: "4c4d5e7aed016f92070516b411d10cc0645e66cc5bb04def7954d051c4509bbd",
    # 0.2.0
    6: "0c4e68c00bd82772730b5844123451cdacb101286383bbf60c1729272f885005",
    7: "54a76e991ba8e00a1c6508c0637187ce9a810addf0d8c2d568fe2ec726fcb18a",
    8: "8773d36545f9da81f9eb411425a0bf349a8cd75754544f3eaacce1da8b3f0367",
    9: "d123d9b3cec3ccba6a64a0b9973c63a8c6b4fa7d3ef71cc0bca52fe36b5d244a",
    10: "18652e9e4ef141551585ccc2c97dba5bea6f7340ca13d0599c3c61c3b7864c12",
    11: "f005a2af75feda5475c5fc1ee5cc3237b1f09a190c8ca1989e49b735f8d77fc1",
    12: "0fd10042b5d31d2f030e1252ca9081663e3e90a8546fcc65551bcae431f92a9c",
    13: "978aaa816ec32bd46004ef472690ead0e09078982f888c429736014ffecd2186",
    # 0.3.0
    14: "bae41795077f5740d0d40cad48540ace394286af5444f5a9d65eb7e742c525fb",
    15: "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    16: "f12f7217f75225fe53d77e872a9d77898121242444383ccfcfe6c0568f4ba56e",
    17: "e8a442d7eb933e2fd5f2c8443dd470cf21bd8cb91ff1ffb5959b21cd95f85009",
}


def fingerprint(number: int) -> str:
    return MIGRATIONS.step(number).fingerprint()


@pytest.mark.parametrize("number", sorted(RELEASED))
def test_a_released_migration_is_never_changed(number: int) -> None:
    assert fingerprint(number) == RELEASED[number], (
        f"migration {number} shipped in a release: make a new one instead"
    )
