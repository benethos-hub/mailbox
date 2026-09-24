"""Users, their tokens and roles, managed through the API.

No escalation: a caller can only hand out rights it holds itself, and can
only manage a user whose rights it holds itself.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from ..data.ids import new_id
from ..data.models import ApiToken, Grant, Role, User
from ..data.storage import RoleRepository, TokenRepository, UserRepository
from ..errors import BadRequestError, ConflictError, ForbiddenError, NotFoundError
from . import permissions
from .access import Access
from .accounts import AccountService
from .auth import AuthService


@dataclass(frozen=True)
class EffectiveRights:
    user_id: str
    name: str
    accounts: dict[str, list[str]]
    operations: list[str]


class UserService:
    def __init__(
        self,
        users: UserRepository,
        roles: RoleRepository,
        tokens: TokenRepository,
        accounts: AccountService,
        auth: AuthService,
    ) -> None:
        self._users = users
        self._roles = roles
        self._tokens = tokens
        self._accounts = accounts
        self._auth = auth

    # --- the caller itself --------------------------------------------------

    def me(self, access: Access) -> EffectiveRights:
        accounts = {}
        for account_id in self._accounts.all_ids():
            operations = access.operations_on(account_id)
            if operations:
                accounts[account_id] = sorted(operations)
        return EffectiveRights(
            user_id=access.user_id,
            name=access.name,
            accounts=accounts,
            operations=sorted(access.general_operations()),
        )

    # --- setup ----------------------------------------------------------------

    def create_admin(self, name: str) -> tuple[User, str]:
        """A user with every right, and a token for it. For the command line
        on the host only: it checks no caller."""
        user = User(
            id=new_id("usr"),
            name=name,
            grants=[Grant(accounts=["*"], allow=[permissions.ADMIN])],
        )
        self._users.save(user)
        _, plain = self._auth.issue_token(user.id, "created on the command line")
        return user, plain

    # --- users ----------------------------------------------------------------

    def list_users(self, access: Access) -> list[User]:
        access.require("list_users")
        return self._users.list()

    def get_user(self, access: Access, user_id: str) -> User:
        access.require("get_user")
        return self._users.get(user_id)

    def create_user(
        self,
        access: Access,
        name: str,
        roles: list[str],
        grants: list[Grant],
    ) -> User:
        access.require("create_user")
        user = User(id=new_id("usr"), name=name, roles=roles, grants=grants)
        self._check_grantable(access, user.roles, user.grants)
        self._users.save(user)
        return user

    def update_user(
        self,
        access: Access,
        user_id: str,
        *,
        name: str | None = None,
        roles: list[str] | None = None,
        grants: list[Grant] | None = None,
        disabled: bool | None = None,
    ) -> User:
        access.require("update_user")
        user = self._users.get(user_id)
        self._require_covers_user(access, user)
        changes = {
            key: value
            for key, value in {
                "name": name,
                "roles": roles,
                "grants": grants,
                "disabled": disabled,
            }.items()
            if value is not None
        }
        updated = user.model_copy(update=changes)
        self._check_grantable(access, updated.roles, updated.grants)
        self._users.save(updated)
        return updated

    def delete_user(self, access: Access, user_id: str) -> None:
        access.require("delete_user")
        user = self._users.get(user_id)
        self._require_covers_user(access, user)
        if user_id == access.user_id:
            raise ConflictError("a user cannot delete itself")
        self._tokens.delete_for_user(user_id)
        self._users.delete(user_id)

    # --- tokens ---------------------------------------------------------------

    def list_tokens(self, access: Access, user_id: str) -> list[ApiToken]:
        access.require("list_tokens")
        self._users.get(user_id)
        return self._tokens.list_for_user(user_id)

    def create_token(
        self,
        access: Access,
        user_id: str,
        name: str,
        expires_at: datetime | None = None,
    ) -> tuple[ApiToken, str]:
        access.require("create_token")
        self._require_covers_user(access, self._users.get(user_id))
        return self._auth.issue_token(user_id, name, expires_at)

    def revoke_token(self, access: Access, user_id: str, token_id: str) -> ApiToken:
        access.require("revoke_token")
        self._require_covers_user(access, self._users.get(user_id))
        if self._tokens.get(token_id).user_id != user_id:
            raise NotFoundError(f"token {token_id} not found")
        return self._auth.revoke_token(token_id)

    # --- roles ----------------------------------------------------------------

    def list_roles(self, access: Access) -> list[Role]:
        access.require("list_roles")
        return self._roles.list()

    def get_role(self, access: Access, role_id: str) -> Role:
        access.require("get_role")
        return self._roles.get(role_id)

    def create_role(self, access: Access, role_id: str, grants: list[Grant]) -> Role:
        access.require("create_role")
        if role_id in {role.id for role in self._roles.list()}:
            raise ConflictError(f"role {role_id} exists")
        return self._save_role(access, Role(id=role_id, grants=grants))

    def replace_role(self, access: Access, role_id: str, grants: list[Grant]) -> Role:
        access.require("replace_role")
        self._require_covers(access, self._roles.get(role_id).grants)
        return self._save_role(access, Role(id=role_id, grants=grants))

    def delete_role(self, access: Access, role_id: str) -> None:
        access.require("delete_role")
        role = self._roles.get(role_id)
        self._require_covers(access, role.grants)
        users = [user.id for user in self._users.list() if role_id in user.roles]
        if users:
            raise ConflictError(f"role {role_id} is used by {', '.join(users)}")
        self._roles.delete(role_id)

    # --- rules ----------------------------------------------------------------

    def _save_role(self, access: Access, role: Role) -> Role:
        _validate(role.grants)
        self._require_covers(access, role.grants)
        self._roles.save(role)
        return role

    def _check_grantable(
        self, access: Access, role_ids: list[str], grants: list[Grant]
    ) -> None:
        _validate(grants)
        self._require_covers(access, [*grants, *self._role_grants(role_ids)])

    def _role_grants(self, role_ids: Iterable[str]) -> list[Grant]:
        grants: list[Grant] = []
        for role_id in role_ids:
            try:
                grants.extend(self._roles.get(role_id).grants)
            except NotFoundError:
                raise BadRequestError(f"unknown role: {role_id}") from None
        return grants

    def _require_covers_user(self, access: Access, user: User) -> None:
        roles = [role for role in user.roles if _exists(self._roles, role)]
        self._require_covers(access, [*user.grants, *self._role_grants(roles)])

    @staticmethod
    def _require_covers(access: Access, grants: list[Grant]) -> None:
        if not access.covers(grants):
            raise ForbiddenError("cannot grant or manage rights the caller lacks")


def _validate(grants: Iterable[Grant]) -> None:
    for grant in grants:
        if not grant.accounts:
            raise BadRequestError("a grant needs at least one account or '*'")
        try:
            permissions.expand(grant.allow)
        except ValueError as exc:
            raise BadRequestError(str(exc)) from None


def _exists(roles: RoleRepository, role_id: str) -> bool:
    try:
        roles.get(role_id)
    except NotFoundError:
        return False
    return True
