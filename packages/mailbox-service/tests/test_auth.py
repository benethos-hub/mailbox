from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service.data.models import Grant, ProviderType, Role, User
from benethos_mailbox_service.data.storage import (
    InMemoryRoleRepository,
    InMemoryTokenRepository,
    InMemoryUserRepository,
)
from benethos_mailbox_service.domain.accounts import AccountService
from benethos_mailbox_service.domain.auth import (
    TOKEN_PREFIX,
    AuthService,
    hash_token,
    new_token,
)
from benethos_mailbox_service.errors import (
    NotFoundError,
    SetupRequiredError,
    UnauthorizedError,
)
from benethos_mailbox_service.main import Services

from .conftest import bearer_for, create_account

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def repos() -> tuple[
    InMemoryUserRepository, InMemoryRoleRepository, InMemoryTokenRepository
]:
    return InMemoryUserRepository(), InMemoryRoleRepository(), InMemoryTokenRepository()


@pytest.fixture
def service(repos, clock: Clock) -> AuthService:
    users, roles, tokens = repos
    users.save(
        User(
            id="usr_reader",
            name="reader",
            roles=["readers"],
            grants=[Grant(accounts=["acc_a"], allow=["accounts.read"])],
        )
    )
    roles.save(
        Role(id="readers", grants=[Grant(accounts=["acc_a"], allow=["mail.read"])])
    )
    return AuthService(users, roles, tokens, clock=clock)


def test_token_format() -> None:
    token = new_token()
    assert token.startswith(TOKEN_PREFIX)
    assert len(token) == len(TOKEN_PREFIX) + 43
    assert token != new_token()


def test_issued_token_authenticates_as_its_user(service: AuthService, repos) -> None:
    record, plain = service.issue_token("usr_reader", "laptop")
    assert record.token_hash == hash_token(plain)
    assert plain not in record.model_dump_json()
    access = service.authenticate(plain)
    assert access.user_id == "usr_reader"
    assert access.allows("list_messages", "acc_a")  # through the role
    assert not access.allows("list_messages", "acc_b")
    assert repos[2].get(record.id).last_used_at == NOW


def test_unknown_token(service: AuthService) -> None:
    with pytest.raises(UnauthorizedError):
        service.authenticate("mbx_nope")


def test_missing_token(service: AuthService) -> None:
    with pytest.raises(UnauthorizedError, match="missing"):
        service.authenticate(None)


def test_revoked_token(service: AuthService) -> None:
    record, plain = service.issue_token("usr_reader", "laptop")
    service.revoke_token(record.id)
    service.revoke_token(record.id)  # idempotent
    with pytest.raises(UnauthorizedError, match="revoked"):
        service.authenticate(plain)


def test_expired_token(service: AuthService, clock: Clock) -> None:
    _, plain = service.issue_token(
        "usr_reader", "t", expires_at=NOW + timedelta(days=1)
    )
    service.authenticate(plain)
    clock.now = NOW + timedelta(days=1)
    with pytest.raises(UnauthorizedError, match="expired"):
        service.authenticate(plain)


def test_disabled_user(service: AuthService, repos) -> None:
    _, plain = service.issue_token("usr_reader", "t")
    users = repos[0]
    users.save(users.get("usr_reader").model_copy(update={"disabled": True}))
    with pytest.raises(UnauthorizedError, match="disabled"):
        service.authenticate(plain)


def test_deleted_user(service: AuthService, repos) -> None:
    _, plain = service.issue_token("usr_reader", "t")
    repos[0].save(User(id="usr_other", name="other"))
    repos[0].delete("usr_reader")
    with pytest.raises(UnauthorizedError):
        service.authenticate(plain)


def test_token_for_unknown_user(service: AuthService) -> None:
    with pytest.raises(NotFoundError):
        service.issue_token("usr_ghost", "t")


def test_admin_key(repos) -> None:
    service = AuthService(*repos, admin_key="the-key")
    access = service.authenticate("the-key")
    assert access.allows("delete_account", "acc_any")
    with pytest.raises(UnauthorizedError):
        service.authenticate("not-the-key")


def test_nothing_configured_asks_for_setup(repos) -> None:
    with pytest.raises(SetupRequiredError, match="create-admin"):
        AuthService(*repos).authenticate("anything")


# --- through the API -------------------------------------------------------


@pytest.fixture
def two_accounts(accounts: AccountService) -> tuple[str, str]:
    a = create_account(accounts, ProviderType.MEMORY, "a@example.com").id
    b = create_account(accounts, ProviderType.MEMORY, "b@example.com").id
    return a, b


def test_list_accounts_shows_only_granted(
    app_client: TestClient, services: Services, two_accounts: tuple[str, str]
) -> None:
    a, _ = two_accounts
    headers = bearer_for(services, Grant(accounts=[a], allow=["accounts.read"]))
    listed = app_client.get("/v1/accounts", headers=headers).json()
    assert [x["id"] for x in listed] == [a]


def test_foreign_account_is_not_found(
    app_client: TestClient, services: Services, two_accounts: tuple[str, str]
) -> None:
    a, b = two_accounts
    headers = bearer_for(services, Grant(accounts=[a], allow=["accounts.read"]))
    response = app_client.get(f"/v1/accounts/{b}", headers=headers)
    assert response.status_code == 404


def test_missing_right_is_forbidden(
    app_client: TestClient, services: Services, two_accounts: tuple[str, str]
) -> None:
    a, _ = two_accounts
    headers = bearer_for(services, Grant(accounts=[a], allow=["accounts.read"]))
    response = app_client.get(f"/v1/accounts/{a}/messages", headers=headers)
    assert response.status_code == 403
    assert response.json()["error"] == {
        "code": "forbidden",
        "message": f"missing right: list_messages on account {a}",
    }


def test_limited_user_cannot_create_accounts(
    app_client: TestClient, services: Services, two_accounts: tuple[str, str]
) -> None:
    a, _ = two_accounts
    headers = bearer_for(services, Grant(accounts=[a], allow=["accounts.manage"]))
    response = app_client.post(
        "/v1/accounts",
        json={"provider": "memory", "email": "x@example.com"},
        headers=headers,
    )
    assert response.status_code == 403
