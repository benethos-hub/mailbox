"""The repositories of accounts, users, roles and tokens: one contract, the
same tests for the in-memory and the SQLite implementation."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

from benethos_mailbox_service.data.models import (
    Account,
    AccountStatus,
    ApiToken,
    Grant,
    ProviderType,
    Role,
    User,
)
from benethos_mailbox_service.data.storage import (
    AccountRepository,
    Database,
    InMemoryAccountRepository,
    InMemoryRoleRepository,
    InMemoryTokenRepository,
    InMemoryUserRepository,
    RoleRepository,
    SqliteAccountRepository,
    SqliteRoleRepository,
    SqliteTokenRepository,
    SqliteUserRepository,
    TokenRepository,
    UserRepository,
)
from benethos_mailbox_service.errors import ConflictError, NotFoundError

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


@dataclass(frozen=True)
class Stores:
    accounts: AccountRepository
    users: UserRepository
    roles: RoleRepository
    tokens: TokenRepository


@pytest.fixture(params=["memory", "sqlite"])
def stores(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[Stores]:
    if request.param == "memory":
        yield Stores(
            InMemoryAccountRepository(),
            InMemoryUserRepository(),
            InMemoryRoleRepository(),
            InMemoryTokenRepository(),
        )
        return
    db = Database(tmp_path / "test.db")
    yield Stores(
        SqliteAccountRepository(db),
        SqliteUserRepository(db),
        SqliteRoleRepository(db),
        SqliteTokenRepository(db),
    )
    db.close()


def test_accounts_round_trip(stores: Stores) -> None:
    repo = stores.accounts
    account = Account(id="acc_1", provider=ProviderType.IMAP, email="a@example.com")
    repo.add(account, {"host": "imap.example.com", "port": 993, "tls": True})
    assert repo.list() == [account]
    assert repo.get("acc_1") == account
    assert repo.settings("acc_1") == {
        "host": "imap.example.com",
        "port": 993,
        "tls": True,
    }
    repo.set_status("acc_1", AccountStatus.UNREACHABLE)
    assert repo.get("acc_1").status is AccountStatus.UNREACHABLE
    repo.update(account.model_copy(update={"display_name": "Me"}), {"host": "h"})
    assert repo.get("acc_1").display_name == "Me"
    assert repo.settings("acc_1") == {"host": "h"}
    repo.delete("acc_1")
    assert repo.list() == []
    for call in (
        lambda: repo.get("acc_1"),
        lambda: repo.settings("acc_1"),
        lambda: repo.delete("acc_1"),
        lambda: repo.set_status("acc_1", AccountStatus.CONNECTED),
        lambda: repo.update(account, {}),
    ):
        with pytest.raises(NotFoundError, match="account acc_1 not found"):
            call()


def test_an_account_id_is_taken_once(stores: Stores) -> None:
    account = Account(id="acc_1", provider=ProviderType.IMAP, email="a@example.com")
    stores.accounts.add(account)
    with pytest.raises(ConflictError):
        stores.accounts.add(account.model_copy(update={"email": "b@example.com"}))
    assert stores.accounts.get("acc_1").email == "a@example.com"


def test_users_round_trip(stores: Stores) -> None:
    repo = stores.users
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
    with pytest.raises(NotFoundError, match="user usr_1 not found"):
        repo.get("usr_1")
    with pytest.raises(NotFoundError):
        repo.delete("usr_1")


def test_roles_round_trip(stores: Stores) -> None:
    repo = stores.roles
    role = Role(id="reader", grants=[Grant(accounts=["acc_a"], allow=["mail.read"])])
    repo.save(role)
    repo.save(role)
    assert repo.list() == [role]
    assert repo.get("reader") == role
    repo.delete("reader")
    with pytest.raises(NotFoundError, match="role reader not found"):
        repo.get("reader")
    with pytest.raises(NotFoundError):
        repo.delete("reader")


def test_tokens_round_trip(stores: Stores) -> None:
    stores.users.save(User(id="usr_1", name="u"))
    repo = stores.tokens
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
    assert repo.list_for_user("usr_2") == []
    with pytest.raises(NotFoundError, match="token tok_9 not found"):
        repo.get("tok_9")
    repo.delete_for_user("usr_1")
    assert repo.list_for_user("usr_1") == []
    with pytest.raises(NotFoundError):
        repo.get("tok_1")
