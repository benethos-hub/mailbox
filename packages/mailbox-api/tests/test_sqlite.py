from __future__ import annotations

import os
import sqlite3
import stat
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from benethos_mailbox_api.__main__ import main
from benethos_mailbox_api.config import Settings
from benethos_mailbox_api.data.models import (
    Account,
    ApiToken,
    Grant,
    ProviderType,
    Role,
    User,
)
from benethos_mailbox_api.data.storage import (
    Database,
    SqliteAccountRepository,
    SqliteRoleRepository,
    SqliteTokenRepository,
    SqliteUserRepository,
)
from benethos_mailbox_api.data.storage.sqlite import SCHEMA_VERSION
from benethos_mailbox_api.errors import NotFoundError
from benethos_mailbox_api.main import build_services

from .conftest import create_account

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


@pytest.fixture
def db(tmp_path: Path) -> Iterator[Database]:
    database = Database(tmp_path / "sub" / "test.db")
    yield database
    database.close()


def test_schema_is_migrated(db: Database) -> None:
    assert db.schema_version() == SCHEMA_VERSION


def test_a_newer_schema_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "new.db"
    Database(path).close()
    raw = sqlite3.connect(path)
    with raw:
        raw.execute("UPDATE meta SET value = '999' WHERE key = 'schema_version'")
    raw.close()
    with pytest.raises(RuntimeError, match="newer"):
        Database(path)


def test_accounts_round_trip(db: Database) -> None:
    repo = SqliteAccountRepository(db)
    account = Account(id="acc_1", provider=ProviderType.IMAP, email="a@example.com")
    repo.add(account, {"host": "imap.example.com", "port": 993, "tls": True})
    assert repo.list() == [account]
    assert repo.get("acc_1") == account
    assert repo.settings("acc_1") == {
        "host": "imap.example.com",
        "port": 993,
        "tls": True,
    }
    repo.delete("acc_1")
    assert repo.list() == []
    with pytest.raises(NotFoundError):
        repo.get("acc_1")
    with pytest.raises(NotFoundError):
        repo.settings("acc_1")
    with pytest.raises(NotFoundError):
        repo.delete("acc_1")


def test_users_round_trip(db: Database) -> None:
    repo = SqliteUserRepository(db)
    user = User(
        id="usr_1",
        name="dashboard",
        roles=["reader"],
        grants=[Grant(accounts=["*"], allow=["mail.read"])],
    )
    repo.save(user)
    assert repo.get("usr_1") == user
    assert repo.count() == 1
    repo.save(user.model_copy(update={"disabled": True, "name": "renamed"}))
    assert repo.list()[0].disabled is True
    assert repo.list()[0].name == "renamed"
    repo.delete("usr_1")
    assert repo.count() == 0
    with pytest.raises(NotFoundError):
        repo.get("usr_1")
    with pytest.raises(NotFoundError):
        repo.delete("usr_1")


def test_roles_round_trip(db: Database) -> None:
    repo = SqliteRoleRepository(db)
    role = Role(id="reader", grants=[Grant(accounts=["acc_a"], allow=["mail.read"])])
    repo.save(role)
    repo.save(role)
    assert repo.list() == [role]
    assert repo.get("reader") == role
    repo.delete("reader")
    with pytest.raises(NotFoundError):
        repo.get("reader")
    with pytest.raises(NotFoundError):
        repo.delete("reader")


def test_tokens_round_trip_and_cascade(db: Database) -> None:
    SqliteUserRepository(db).save(User(id="usr_1", name="u"))
    repo = SqliteTokenRepository(db)
    token = ApiToken(
        id="tok_1", user_id="usr_1", name="t", token_hash="h", created_at=NOW
    )
    repo.save(token)
    used = token.model_copy(update={"last_used_at": NOW})
    repo.save(used)
    assert repo.get("tok_1") == used
    assert repo.find_by_hash("h") == used
    assert repo.find_by_hash("other") is None
    assert repo.list_for_user("usr_1") == [used]
    SqliteUserRepository(db).delete("usr_1")
    assert repo.list_for_user("usr_1") == []
    with pytest.raises(NotFoundError):
        repo.get("tok_1")


def test_delete_for_user(db: Database) -> None:
    SqliteUserRepository(db).save(User(id="usr_1", name="u"))
    repo = SqliteTokenRepository(db)
    repo.save(
        ApiToken(id="t", user_id="usr_1", name="t", token_hash="h", created_at=NOW)
    )
    repo.delete_for_user("usr_1")
    assert repo.list_for_user("usr_1") == []


def test_a_failed_transaction_rolls_back(db: Database) -> None:
    with pytest.raises(RuntimeError), db.transaction() as conn:
        conn.execute("INSERT INTO roles (id, grants) VALUES ('r', '[]')")
        raise RuntimeError("abort")
    assert db.query("SELECT COUNT(*) FROM roles")[0][0] == 0


def test_everything_survives_a_restart(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, storage="sqlite")
    first = build_services(settings)
    account = create_account(first.accounts, ProviderType.MEMORY, "a@example.com")
    user, token = first.users.create_admin("owner")

    first.close()

    second = build_services(settings)
    access = second.auth.authenticate(token)
    assert access.user_id == user.id
    assert second.accounts.get(access, account.id) == account
    # The adapter is rebuilt from the stored record on first use.
    assert second.accounts.provider(account.id) is second.accounts.provider(account.id)
    second.close()


def test_create_admin_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("MAILBOX_API_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MAILBOX_API_STORAGE", "sqlite")
    assert main(["users", "create-admin", "--name", "owner"]) == 0
    out, err = capsys.readouterr()
    token = out.strip()
    assert token.startswith("mbx_")
    assert "shown this once" in err
    services = build_services(Settings())
    access = services.auth.authenticate(token)
    services.close()
    assert access.name == "owner"
    assert access.allows("create_user")


def test_a_missing_data_folder_is_created(tmp_path: Path) -> None:
    data_dir = tmp_path / "data" / "benethos-mailbox-api"
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
