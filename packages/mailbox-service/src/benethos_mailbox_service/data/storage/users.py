"""Users, roles and API tokens of the service."""

from __future__ import annotations

from typing import Protocol

from ...errors import ConflictError
from ..models import ApiToken, Role, User
from .table import Table, TableRepository


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
    """``save`` adds or replaces a token as a whole. A hash is held by one
    token at most, a second one is a conflict."""

    def list_for_user(self, user_id: str) -> list[ApiToken]: ...

    def get(self, token_id: str) -> ApiToken: ...

    def find_by_hash(self, token_hash: str) -> ApiToken | None: ...

    def save(self, token: ApiToken) -> None: ...

    def delete_for_user(self, user_id: str) -> None: ...


class InMemoryUserRepository(TableRepository[User]):
    def __init__(self) -> None:
        super().__init__("user")

    def count(self) -> int:
        return len(self._rows)


class InMemoryRoleRepository(TableRepository[Role]):
    def __init__(self) -> None:
        super().__init__("role")


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
        other = self.find_by_hash(token.token_hash)
        if other is not None and other.id != token.id:
            raise ConflictError(f"token {other.id} has the same hash")
        self._tokens.put(token.id, token)

    def delete_for_user(self, user_id: str) -> None:
        for token in self.list_for_user(user_id):
            self._tokens.delete(token.id)
