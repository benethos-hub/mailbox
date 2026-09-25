"""Users, roles and API tokens of the service."""

from __future__ import annotations

from typing import Protocol

from ..models import ApiToken, Role, User
from .table import Table


class UserRepository(Protocol):
    def list(self) -> list[User]: ...

    def get(self, user_id: str) -> User: ...

    def save(self, user: User) -> None: ...

    def delete(self, user_id: str) -> None: ...

    def count(self) -> int: ...


class RoleRepository(Protocol):
    def list(self) -> list[Role]: ...

    def get(self, role_id: str) -> Role: ...

    def save(self, role: Role) -> None: ...

    def delete(self, role_id: str) -> None: ...


class TokenRepository(Protocol):
    def list_for_user(self, user_id: str) -> list[ApiToken]: ...

    def get(self, token_id: str) -> ApiToken: ...

    def find_by_hash(self, token_hash: str) -> ApiToken | None: ...

    def save(self, token: ApiToken) -> None: ...

    def delete_for_user(self, user_id: str) -> None: ...


class InMemoryUserRepository:
    def __init__(self) -> None:
        self._users: Table[User] = Table("user")

    def list(self) -> list[User]:
        return self._users.list()

    def get(self, user_id: str) -> User:
        return self._users.get(user_id)

    def save(self, user: User) -> None:
        self._users.put(user.id, user)

    def delete(self, user_id: str) -> None:
        self._users.delete(user_id)

    def count(self) -> int:
        return len(self._users)


class InMemoryRoleRepository:
    def __init__(self) -> None:
        self._roles: Table[Role] = Table("role")

    def list(self) -> list[Role]:
        return self._roles.list()

    def get(self, role_id: str) -> Role:
        return self._roles.get(role_id)

    def save(self, role: Role) -> None:
        self._roles.put(role.id, role)

    def delete(self, role_id: str) -> None:
        self._roles.delete(role_id)


class InMemoryTokenRepository:
    def __init__(self) -> None:
        self._tokens: Table[ApiToken] = Table("token")

    def list_for_user(self, user_id: str) -> list[ApiToken]:
        return [t for t in self._tokens.list() if t.user_id == user_id]

    def get(self, token_id: str) -> ApiToken:
        return self._tokens.get(token_id)

    def find_by_hash(self, token_hash: str) -> ApiToken | None:
        return next(
            (t for t in self._tokens.list() if t.token_hash == token_hash), None
        )

    def save(self, token: ApiToken) -> None:
        self._tokens.put(token.id, token)

    def delete_for_user(self, user_id: str) -> None:
        for token in self.list_for_user(user_id):
            self._tokens.delete(token.id)
