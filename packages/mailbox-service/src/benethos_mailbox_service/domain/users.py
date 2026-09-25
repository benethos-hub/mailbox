"""Users, their tokens and roles, managed through the API.

No escalation: a caller can only hand out rights it holds itself, and can
only manage a user whose rights it holds itself.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from ..common.ids import new_id
from ..data.models import ApiToken, Grant, Role, User
from ..data.storage import RoleRepository, TokenRepository, UserRepository
from ..errors import BadRequestError, ConflictError, ForbiddenError, NotFoundError
from . import permissions
from .access import Access, SendLimit
from .adapters import Adapters
from .auth import AuthService, TokenState


@dataclass(frozen=True)
class AccountRights:
    """One account the caller may act on, and what it may do there."""

    id: str
    email: str
    display_name: str | None
    operations: list[str]
    warnings: list[str]
    # One entry per grant that allows sending here. A send passes when one
    # of them allows it. Empty when no grant allows sending.
    sending: list[SendLimit]


@dataclass(frozen=True)
class EffectiveRights:
    user_id: str
    name: str
    accounts: list[AccountRights]
    operations: list[str]


class UserService:
    def __init__(
        self,
        users: UserRepository,
        roles: RoleRepository,
        tokens: TokenRepository,
        adapters: Adapters,
        auth: AuthService,
    ) -> None:
        self._users = users
        self._roles = roles
        self._tokens = tokens
        self._adapters = adapters
        self._auth = auth

    # --- the caller itself --------------------------------------------------

    def me(self, access: Access) -> EffectiveRights:
        return self._effective(access, visible_to=None)

    def rights_of(self, access: Access, user_id: str) -> EffectiveRights:
        """What a user may do, its direct grants and those of its roles
        together. Only accounts the caller can see are listed."""
        access.require("get_user")
        user = self._users.get(user_id)
        roles = {role.id: role for role in self._roles.list()}
        return self._effective(Access.for_user(user, roles), visible_to=access)

    def _effective(self, access: Access, visible_to: Access | None) -> EffectiveRights:
        accounts = []
        for account_id in self._adapters.ids():
            if visible_to is not None and not visible_to.sees(account_id):
                continue
            operations = access.operations_on(account_id)
            if operations:
                account = self._adapters.record(account_id)
                accounts.append(
                    AccountRights(
                        id=account.id,
                        email=account.email,
                        display_name=account.display_name,
                        operations=sorted(operations),
                        warnings=_warnings(access, account_id, operations),
                        sending=access.send_limits("send_message", account_id),
                    )
                )
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
        _named("a user", name)
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
        if name is not None:
            _named("a user", name)
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

    def token_state(self, token: ApiToken) -> TokenState:
        """Active, expired or revoked, by the service's clock."""
        return self._auth.state_of(token)

    def create_token(
        self,
        access: Access,
        user_id: str,
        name: str,
        expires_at: datetime | None = None,
    ) -> tuple[ApiToken, str]:
        access.require("create_token")
        _named("a token", name)
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
        _named("a role", role_id)
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
        users = [user.id for user in self._holders(role_id)]
        if users:
            raise ConflictError(f"role {role_id} is used by {', '.join(users)}")
        self._roles.delete(role_id)

    def holders_of(self, access: Access, role_id: str) -> list[User]:
        """The users that hold a role."""
        access.require("list_users")
        self._roles.get(role_id)
        return self._holders(role_id)

    def _holders(self, role_id: str) -> list[User]:
        return [user for user in self._users.list() if role_id in user.roles]

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


def _named(what: str, name: str) -> None:
    if not name.strip():
        raise BadRequestError(f"{what} needs a name")


def _validate(grants: Iterable[Grant]) -> None:
    for grant in grants:
        if not grant.accounts:
            raise BadRequestError("a grant needs at least one account or '*'")
        permissions.expand(grant.allow)


def _exists(roles: RoleRepository, role_id: str) -> bool:
    try:
        roles.get(role_id)
    except NotFoundError:
        return False
    return True


# Read mail, and send it to any address: what an injected instruction in a
# mail needs to carry data out (CONCEPT 7.7). A warning, not a block.
READ_AND_SEND_ANYWHERE = "read_and_send_anywhere"


def _warnings(access: Access, account_id: str, operations: frozenset[str]) -> list[str]:
    if "get_message" in operations and access.sends_anywhere(account_id):
        return [READ_AND_SEND_ANYWHERE]
    return []
