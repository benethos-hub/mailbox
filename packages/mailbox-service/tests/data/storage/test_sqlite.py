from __future__ import annotations

import asyncio
import hashlib
import importlib
import json
import os
import pkgutil
import re
import sqlite3
import stat
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from benethos_mailbox_service.__main__ import main
from benethos_mailbox_service.common.clock import iso
from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.models import ApiToken, ProviderType, User
from benethos_mailbox_service.data.storage import (
    Database,
    SqliteRoleRepository,
    SqliteTokenRepository,
    SqliteUserRepository,
)
from benethos_mailbox_service.data.storage.sqlite import SCHEMA_VERSION, migrations
from benethos_mailbox_service.data.storage.sqlite.migrations import MIGRATIONS
from benethos_mailbox_service.domain.rights import Access
from benethos_mailbox_service.errors import (
    ConflictError,
    NotFoundError,
    StorageError,
    UnauthorizedError,
)
from benethos_mailbox_service.main import build_services

from ...conftest import CHEAP, create_account

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


@pytest.fixture
def db(tmp_path: Path) -> Iterator[Database]:
    database = Database(tmp_path / "sub" / "test.db")
    yield database
    database.close()


def test_schema_is_migrated(db: Database) -> None:
    assert db.schema_version() == SCHEMA_VERSION


def test_webhooks_of_users_deleted_before_are_dropped(tmp_path: Path) -> None:
    path = tmp_path / "old.db"
    Database(path).close()
    raw = sqlite3.connect(path)
    with raw:
        raw.execute("ALTER TABLE users DROP COLUMN service")
        raw.execute("ALTER TABLE roles DROP COLUMN service")
        raw.execute("ALTER TABLE changes DROP COLUMN folder_id")
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


def test_deleting_a_user_cascades_to_its_tokens(db: Database) -> None:
    SqliteUserRepository(db).save(User(id="usr_1", name="u"))
    repo = SqliteTokenRepository(db)
    repo.save(
        ApiToken(id="tok_1", user_id="usr_1", name="t", token_hash="h", created_at=NOW)
    )
    SqliteUserRepository(db).delete("usr_1")
    assert repo.list_for_user("usr_1") == []
    with pytest.raises(NotFoundError):
        repo.get("tok_1")


def test_a_failed_transaction_rolls_back(db: Database) -> None:
    with pytest.raises(RuntimeError), db.transaction() as conn:
        conn.execute("INSERT INTO roles (id, grants) VALUES ('r', '[]')")
        raise RuntimeError("abort")
    assert db.query("SELECT COUNT(*) FROM roles")[0][0] == 0


def test_a_failed_commit_leaves_no_open_transaction(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Failing:
        """The connection, whose COMMIT fails."""

        def __init__(self, real: sqlite3.Connection) -> None:
            self._real = real

        def execute(self, sql: str, *args: object) -> object:
            if sql == "COMMIT":
                raise sqlite3.OperationalError("disk I/O error")
            return self._real.execute(sql, *args)

        def __getattr__(self, name: str) -> object:
            return getattr(self._real, name)

    monkeypatch.setattr(db, "_connection", Failing(db._connection))
    with pytest.raises(StorageError, match="disk I/O error"), db.transaction() as c:
        c.execute("INSERT INTO roles (id, grants) VALUES ('r', '[]')")
    monkeypatch.undo()
    assert not db._connection.in_transaction
    assert db.query("SELECT COUNT(*) FROM roles")[0][0] == 0


def test_a_transaction_inside_another_is_a_savepoint(db: Database) -> None:
    with db.transaction() as outer:
        outer.execute("INSERT INTO roles (id, grants) VALUES ('kept', '[]')")
        with pytest.raises(RuntimeError), db.transaction() as inner:
            inner.execute("INSERT INTO roles (id, grants) VALUES ('undone', '[]')")
            raise RuntimeError("abort")
        with db.transaction() as inner:
            inner.execute("INSERT INTO roles (id, grants) VALUES ('also', '[]')")
    assert [r[0] for r in db.query("SELECT id FROM roles ORDER BY id")] == [
        "also",
        "kept",
    ]


def test_sqlite_failures_are_translated(db: Database) -> None:
    with pytest.raises(StorageError, match="no such table"):
        db.query("SELECT * FROM nope")
    with pytest.raises(StorageError, match="no such table"):
        db.one("SELECT * FROM nope")
    with pytest.raises(StorageError, match="no such table"):
        db.execute("DELETE FROM nope")
    with pytest.raises(ConflictError, match="FOREIGN KEY"):
        db.execute(
            "INSERT INTO tokens (id, user_id, name, token_hash, created_at)"
            " VALUES ('t', 'nobody', 'n', 'h', 'now')"
        )
    with pytest.raises(ConflictError, match="UNIQUE"):
        for _ in range(2):
            db.execute("INSERT INTO roles (id, grants) VALUES ('r', '[]')")


def test_the_index_of_a_deleted_account_is_a_conflict(db: Database) -> None:
    from benethos_mailbox_service.data.storage import (
        IndexChanges,
        IndexEntry,
        SqliteMessageIndexRepository,
    )

    index = SqliteMessageIndexRepository(db)
    changes = IndexChanges(added=[IndexEntry("msg_1", "n1", "INBOX")])
    with pytest.raises(ConflictError):
        index.apply("acc_gone", changes)


def test_everything_survives_a_restart(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, storage="sqlite")
    first = build_services(settings, password_hasher=CHEAP)
    account = create_account(first.accounts, ProviderType.MEMORY, "a@example.com")
    user, password = asyncio.run(first.users.create_admin("owner"))
    _, token = first.auth.issue_token(user.id, "t")

    first.close()

    second = build_services(settings, password_hasher=CHEAP)
    signed = asyncio.run(second.auth.sign_in("owner", password, source="host"))
    assert signed.user_id == user.id
    access = second.auth.authenticate(token)
    assert access.user_id == user.id
    assert second.accounts.get(access, account.id) == account
    # The adapter is rebuilt from the stored record on first use.
    assert second.adapters.get(account.id) is second.adapters.get(account.id)
    second.close()


def test_create_admin_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("MAILBOX_SERVICE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MAILBOX_SERVICE_STORAGE", "sqlite")
    assert main(["users", "create-admin", "--name", "owner"]) == 0
    out, err = capsys.readouterr()
    password = out.strip()
    assert len(password) >= 15 and "\n" not in password
    assert "one-time password, shown this once" in err
    services = build_services(Settings())
    signed = asyncio.run(services.auth.sign_in("owner", password, source="host"))
    access = services.auth.session_access(signed.user_id, signed.stamp)
    services.close()
    # A one-time password: the UI asks for one of the user's own first.
    assert signed.must_change is True
    assert access.name == "owner"
    assert access.allows("create_user")

    # A second admin of the same name is refused, and says so.
    assert main(["users", "create-admin", "--name", "Owner"]) == 1
    assert "a user named owner exists" in capsys.readouterr().err


@pytest.mark.parametrize(
    "command",
    [["users", "create-admin"], ["users", "set-password", "admin"], ["keys", "init"]],
)
def test_commands_that_write_need_a_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: list[str],
) -> None:
    monkeypatch.setenv("MAILBOX_SERVICE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MAILBOX_SERVICE_STORAGE", "memory")
    monkeypatch.setenv("MAILBOX_SERVICE_KEY_PROVIDER", "file")
    monkeypatch.setenv("MAILBOX_SERVICE_KEY_FILE", str(tmp_path / "master.key"))
    assert main(command) == 1
    assert "need MAILBOX_SERVICE_STORAGE=sqlite" in capsys.readouterr().err
    assert not (tmp_path / "master.key").exists()


def test_set_password_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("MAILBOX_SERVICE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MAILBOX_SERVICE_STORAGE", "sqlite")
    assert main(["users", "create-admin"]) == 0
    first = capsys.readouterr().out.strip()
    assert main(["users", "set-password", "ADMIN"]) == 0
    out, err = capsys.readouterr()
    second = out.strip()
    assert second != first and "a new password" in err
    services = build_services(Settings())
    signed = asyncio.run(services.auth.sign_in("admin", second, source="host"))
    assert signed.must_change is True
    with pytest.raises(UnauthorizedError):
        asyncio.run(services.auth.sign_in("admin", first, source="host"))
    services.close()
    assert main(["users", "set-password", "nobody"]) == 1
    assert "no user is named nobody" in capsys.readouterr().err


def test_a_missing_data_folder_is_created(tmp_path: Path) -> None:
    data_dir = tmp_path / "data" / "benethos-mailbox-service"
    services = build_services(Settings(data_dir=data_dir, storage="sqlite"))
    try:
        assert (data_dir / "mailbox.db").is_file()
    finally:
        services.close()


POSIX_ONLY = pytest.mark.skipif(os.name != "posix", reason="file modes are POSIX")


def test_the_database_file_is_created(tmp_path: Path) -> None:
    path = tmp_path / "sub" / "mailbox.db"
    Database(path).close()
    assert path.is_file()


@POSIX_ONLY
def test_the_database_file_is_the_owners_alone(tmp_path: Path) -> None:
    path = tmp_path / "mailbox.db"
    Database(path).close()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@POSIX_ONLY
def test_a_readable_database_file_is_narrowed(tmp_path: Path) -> None:
    path = tmp_path / "mailbox.db"
    Database(path).close()
    path.chmod(0o644)
    Database(path).close()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_times_are_stored_in_utc() -> None:
    earlier = iso(datetime.fromisoformat("2026-09-27T14:00:00+02:00"))
    later = iso(datetime(2026, 9, 27, 12, 30, tzinfo=UTC))
    assert earlier == "2026-09-27T12:00:00+00:00"
    # Stored in UTC, the earlier time sorts first as text too.
    assert earlier is not None and later is not None and earlier < later
    with pytest.raises(ValueError, match="without a zone"):
        iso(datetime(2026, 9, 27, 12, 0))


def test_each_migration_step_is_one_statement() -> None:
    """Executed one by one: a second statement in a step would be cut off
    by sqlite3, one that ended early would be refused."""
    for number, migration in enumerate(MIGRATIONS, 1):
        for step in migration.statements:
            assert not sqlite3.complete_statement(step), (number, step)
            assert sqlite3.complete_statement(step + ";"), (number, step)


def test_each_migration_module_is_in_the_list_at_its_number() -> None:
    """A module left out of MIGRATIONS, or one at the wrong place, would
    change the schema a version stands for."""
    found = {
        module.name: importlib.import_module(f"{migrations.__name__}.{module.name}")
        for module in pkgutil.iter_modules(migrations.__path__)
        if module.name != "step"
    }
    numbers = []
    for name, module in found.items():
        named = re.fullmatch(r"v(\d{4})_\w+", name)
        assert named, f"{name} is not named vNNNN_<subject>"
        numbers.append(int(named[1]))
        assert module.MIGRATION is MIGRATIONS[numbers[-1] - 1], name
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
}


def fingerprint(number: int) -> str:
    statements = MIGRATIONS[number - 1].statements
    return hashlib.sha256("\n;\n".join(statements).encode()).hexdigest()


@pytest.mark.parametrize("number", sorted(RELEASED))
def test_a_released_migration_is_never_changed(number: int) -> None:
    assert fingerprint(number) == RELEASED[number], (
        f"migration {number} shipped in a release: make a new one instead"
    )


# --- the file shrinks ------------------------------------------------------------


def _pages(db: Database) -> tuple[int, int]:
    """Pages in the file, and pages on its free list."""
    count = db.one("PRAGMA page_count")
    free = db.one("PRAGMA freelist_count")
    assert count is not None and free is not None
    return int(count[0]), int(free[0])


def test_a_new_database_shrinks_after_a_deletion(tmp_path: Path) -> None:
    path = tmp_path / "grows.db"
    db = Database(path)
    try:
        assert db.migrated is not None and db.migrated.before == 0
        assert "rewritten" not in " ".join(db.migrated.notes)
        with db.transaction() as conn:
            conn.execute("CREATE TABLE bulk (payload BLOB)")
            conn.executemany("INSERT INTO bulk VALUES (?)", [(b"x" * 4096,)] * 500)
        full, _ = _pages(db)
        with db.transaction() as conn:
            conn.execute("DELETE FROM bulk")
        db.shrink()
        after, free = _pages(db)
        assert free == 0
        assert after < full / 4
        assert path.stat().st_size < full * 4096
    finally:
        db.close()


def test_an_older_database_is_rewritten_once_to_shrink(tmp_path: Path) -> None:
    path = tmp_path / "old.db"
    Database(path).close()
    # As a database made before shrinking existed: no auto_vacuum.
    plain = sqlite3.connect(path)
    plain.execute("PRAGMA auto_vacuum = NONE")
    plain.execute("VACUUM")
    assert plain.execute("PRAGMA auto_vacuum").fetchone()[0] == 0
    plain.close()
    db = Database(path)
    try:
        assert db.one("PRAGMA auto_vacuum")[0] == 2  # type: ignore[index]
        assert db.migrated is not None
        assert db.migrated.before == db.migrated.after == SCHEMA_VERSION
        assert any("rewritten once" in note for note in db.migrated.notes)
    finally:
        db.close()
    # Not again.
    db = Database(path)
    try:
        assert db.migrated is None
    finally:
        db.close()


def test_forgetting_an_account_gives_its_pages_back(tmp_path: Path) -> None:
    from benethos_mailbox_service.data.models import Account
    from benethos_mailbox_service.data.storage import (
        IndexEntry,
        SqliteAccountRepository,
        SqliteMessageIndexRepository,
    )

    db = Database(tmp_path / "index.db")
    try:
        SqliteAccountRepository(db).add(
            Account(id="acc_1", provider=ProviderType.IMAP, email="a@example.com")
        )
        index = SqliteMessageIndexRepository(db)
        index.add(
            "acc_1",
            [
                IndexEntry(id=f"msg_{n}", native_id=f"n{n}", folder_id="f_inbox")
                for n in range(3000)
            ],
        )
        full, _ = _pages(db)
        index.forget_account("acc_1")
        after, free = _pages(db)
        assert free == 0
        assert after < full / 2
    finally:
        db.close()
