"""Users, roles and API tokens of the service."""

from __future__ import annotations

from typing import Protocol

from ...errors import NotFoundError
from ..models import ApiToken, Role, User


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
        self._users: dict[str, User] = {}

    def list(self) -> list[User]:
        return list(self._users.values())

    def get(self, user_id: str) -> User:
        try:
            return self._users[user_id]
        except KeyError:
            raise NotFoundError(f"user {user_id} not found") from None

    def save(self, user: User) -> None:
        self._users[user.id] = user

    def delete(self, user_id: str) -> None:
        self.get(user_id)
        del self._users[user_id]

    def count(self) -> int:
        return len(self._users)


class InMemoryRoleRepository:
    def __init__(self) -> None:
        self._roles: dict[str, Role] = {}

    def list(self) -> list[Role]:
        return list(self._roles.values())

    def get(self, role_id: str) -> Role:
        try:
            return self._roles[role_id]
        except KeyError:
            raise NotFoundError(f"role {role_id} not found") from None

    def save(self, role: Role) -> None:
        self._roles[role.id] = role

    def delete(self, role_id: str) -> None:
        self.get(role_id)
        del self._roles[role_id]


class InMemoryTokenRepository:
    def __init__(self) -> None:
        self._tokens: dict[str, ApiToken] = {}

    def list_for_user(self, user_id: str) -> list[ApiToken]:
        return [t for t in self._tokens.values() if t.user_id == user_id]

    def get(self, token_id: str) -> ApiToken:
        try:
            return self._tokens[token_id]
        except KeyError:
            raise NotFoundError(f"token {token_id} not found") from None

    def find_by_hash(self, token_hash: str) -> ApiToken | None:
        for token in self._tokens.values():
            if token.token_hash == token_hash:
                return token
        return None

    def save(self, token: ApiToken) -> None:
        self._tokens[token.id] = token

    def delete_for_user(self, user_id: str) -> None:
        for token in self.list_for_user(user_id):
            del self._tokens[token.id]
