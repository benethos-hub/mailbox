"""Users, their tokens, passwords and roles.

No escalation: a caller can only hand out rights it holds itself, and can
only manage a user whose rights it holds itself.
"""

from __future__ import annotations

import secrets
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime

from ...common.ids import new_id
from ...data.models import AccountStatus, ApiToken, Grant, Role, User
from ...data.storage import (
    RoleRepository,
    TokenRepository,
    UserRepository,
    WebhookRepository,
)
from ...errors import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    missing,
)
from ..accounts import Adapters
from ..activity import HOST, ActivityLog, Actor
from ..activity import users as said
from ..auth import MAX_NAME, AuthService, TokenState
from ..rights import Access, SendLimit, permissions

# A one-time password of 18 random bytes: 24 characters, 144 bits.
ONE_TIME_BYTES = 18


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
    status: AccountStatus = AccountStatus.CONNECTED


@dataclass(frozen=True)
class EffectiveRights:
    user_id: str
    name: str
    accounts: list[AccountRights]
    operations: list[str]
    roles: list[str] = field(default_factory=list)


class UserService:
    def __init__(
        self,
        users: UserRepository,
        roles: RoleRepository,
        tokens: TokenRepository,
        adapters: Adapters,
        auth: AuthService,
        webhooks: WebhookRepository,
        activity: ActivityLog | None = None,
    ) -> None:
        self._users = users
        self._roles = roles
        self._tokens = tokens
        self._adapters = adapters
        self._auth = auth
        self._webhooks = webhooks
        self._activity = activity or auth.activity

    # --- the caller itself --------------------------------------------------

    def me(self, access: Access) -> EffectiveRights:
        return self._effective(access, visible_to=None, roles=list(access.roles))

    def rights_of(self, access: Access, user_id: str) -> EffectiveRights:
        """What a user may do, its direct grants and those of its roles
        together. Only accounts the caller can see are listed."""
        access.require("get_user")
        user = self._users.get(user_id)
        roles = {role.id: role for role in self._roles.list()}
        return self._effective(
            Access.for_user(user, roles), visible_to=access, roles=user.roles
        )

    def _effective(
        self, access: Access, visible_to: Access | None, roles: list[str]
    ) -> EffectiveRights:
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
                        sending=access.sending_limits(account_id),
                        status=account.status,
                    )
                )
        return EffectiveRights(
            user_id=access.user_id,
            name=access.name,
            accounts=accounts,
            operations=sorted(access.general_operations()),
            roles=list(roles),
        )

    # --- setup ----------------------------------------------------------------

    async def create_admin(self, name: str) -> tuple[User, str]:
        """A user with every right, and a one-time password for it, to be
        changed at the first sign-in. For the command line on the host
        only: it checks no caller."""
        name = _named("a user", name)
        self._require_free(name)
        user = User(
            id=new_id("usr"),
            name=name,
            grants=[Grant(accounts=["*"], allow=[permissions.ADMIN])],
            ui_sign_in=True,
        )
        self._users.save(user)
        self._activity.record(said.UserCreated(by=HOST, user=user))
        return user, await self._one_time(user)

    async def reset_password(self, name: str) -> tuple[User, str]:
        """A new one-time password for the user of this name, to be changed
        at the next sign-in. For the command line on the host only, when
        nobody who could set it can sign in: it checks no caller. An API
        user may sign in to the UI from now on."""
        user = self._auth.user_named(name)
        if user is None:
            raise NotFoundError(f"no user is named {name}")
        if not user.ui_sign_in:
            user = user.model_copy(update={"ui_sign_in": True})
            self._users.save(user)
            self._activity.record(said.UiSignInAllowed(by=HOST, user=user))
        return user, await self._one_time(user)

    async def _one_time(self, user: User) -> str:
        password = await self._force(user, None, HOST)
        assert password is not None
        return password

    async def _force(self, user: User, new: str | None, by: Actor) -> str | None:
        """A password the user must change at its next sign-in: ``new``, or
        without it a random one, which is returned to be shown once."""
        password = secrets.token_urlsafe(ONE_TIME_BYTES) if new is None else new
        await self._auth.passwords.set(user.id, user.name, password, must_change=True)
        self._activity.record(said.PasswordSet(by=by, user=user, one_time=new is None))
        return password if new is None else None

    # --- users ----------------------------------------------------------------

    def list_users(
        self,
        access: Access,
        *,
        name: str | None = None,
        role: str | None = None,
        disabled: bool | None = None,
        ui_sign_in: bool | None = None,
    ) -> list[User]:
        """Every user, or those whose name holds ``name`` regardless of
        case, that hold ``role``, that are disabled or not, that may sign
        in to the UI or not."""
        access.require("list_users")
        wanted = (name or "").casefold()
        return [
            user
            for user in self._users.list()
            if wanted in user.name.casefold()
            and (role is None or role in user.roles)
            and (disabled is None or user.disabled == disabled)
            and (ui_sign_in is None or user.ui_sign_in == ui_sign_in)
        ]

    def get_user(self, access: Access, user_id: str) -> User:
        access.require("get_user")
        return self._users.get(user_id)

    def create_user(
        self,
        access: Access,
        name: str,
        roles: list[str],
        grants: list[Grant],
        *,
        ui_sign_in: bool = False,
    ) -> User:
        """A new user. Without ``ui_sign_in`` an API user: tokens only."""
        access.require("create_user")
        name = _named("a user", name)
        self._require_free(name)
        user = User(
            id=new_id("usr"),
            name=name,
            roles=roles,
            grants=grants,
            ui_sign_in=ui_sign_in,
        )
        self._check_grantable(access, user.roles, user.grants)
        self._users.save(user)
        self._activity.record(said.UserCreated(by=Actor.of(access), user=user))
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
        ui_sign_in: bool | None = None,
    ) -> User:
        """Switching ``ui_sign_in`` off deletes the password, which ends the
        user's UI sessions. Nobody disables itself or takes its own UI
        sign-in."""
        access.require("update_user")
        if name is not None:
            name = _named("a user", name)
            self._require_free(name, user_id)
        user = self._users.get(user_id)
        self._require_covers_user(access, user)
        if user_id == access.user_id:
            if disabled:
                raise ConflictError("a user cannot disable itself")
            if ui_sign_in is False:
                raise ConflictError("a user cannot take its own UI sign-in")
        changes = {
            key: value
            for key, value in {
                "name": name,
                "roles": roles,
                "grants": grants,
                "disabled": disabled,
                "ui_sign_in": ui_sign_in,
            }.items()
            if value is not None
        }
        updated = user.model_copy(update=changes)
        # Only grants given now must name known rights. A stored one may
        # name a right a release renamed, and grants nothing by it.
        self._check_grantable(access, updated.roles, updated.grants, grants or [])
        self._users.save(updated)
        changed = tuple(
            key for key in changes if getattr(user, key) != getattr(updated, key)
        )
        if changed:
            self._activity.record(
                said.UserChanged(by=Actor.of(access), user=updated, changed=changed)
            )
        if user.ui_sign_in and not updated.ui_sign_in:
            self._auth.passwords.delete(user_id)
            self._activity.record(said.MadeApiUser(by=Actor.of(access), user=user))
        return updated

    def delete_user(self, access: Access, user_id: str) -> None:
        access.require("delete_user")
        user = self._users.get(user_id)
        self._require_covers_user(access, user)
        if user_id == access.user_id:
            raise ConflictError("a user cannot delete itself")
        self._tokens.delete_for_user(user_id)
        self._auth.passwords.delete(user_id)
        # Its webhooks would post by nobody's rights, and nobody could
        # remove them.
        removed = self._webhooks.delete_for_user(user_id)
        self._users.delete(user_id)
        self._activity.record(
            said.UserDeleted(by=Actor.of(access), user=user, webhooks=removed)
        )

    def _require_free(self, name: str, user_id: str | None = None) -> None:
        """A person signs in with the name: one user per name, whatever
        the case."""
        taken = self._auth.user_named(name)
        if taken is not None and taken.id != user_id:
            raise ConflictError(f"a user named {taken.name} exists")

    # --- passwords ------------------------------------------------------------

    def has_password(self, access: Access, user_id: str) -> bool:
        """Whether the user can sign in to the UI."""
        if user_id != access.user_id:
            access.require("get_user")
        return self._auth.passwords.stored(user_id) is not None

    def last_sign_in(self, access: Access, user_id: str) -> datetime | None:
        """When the user last signed in to the UI."""
        if user_id != access.user_id:
            access.require("get_user")
        stored = self._auth.passwords.stored(user_id)
        return stored.last_sign_in_at if stored is not None else None

    async def change_password(self, access: Access, current: str, new: str) -> datetime:
        """The caller's own password, with the current one. Returns the new
        stamp, which keeps the caller's session and ends its others."""
        user = self._users.get(access.user_id)
        if not await self._auth.passwords.matches(user.id, current):
            raise BadRequestError("the current password is not right")
        if new == current:
            raise BadRequestError("the new password is the current one")
        stored = await self._auth.passwords.set(
            user.id, user.name, new, must_change=False
        )
        self._activity.record(said.PasswordChanged(by=Actor.of(access)))
        return stored.updated_at

    async def set_password(
        self, access: Access, user_id: str, new: str | None = None
    ) -> str | None:
        """Another user's password, within the caller's rights: whoever sets
        it can sign in as that user. Without ``new`` the service makes a
        one-time password and returns it, to be shown once. Either must be
        changed at the next sign-in."""
        user = self._settable(access, user_id)
        return await self._force(user, new, Actor.of(access))

    async def one_time_password(self, access: Access, user_id: str) -> str:
        """``set_password`` without a password: the one the service made."""
        password = await self.set_password(access, user_id)
        assert password is not None
        return password

    def _settable(self, access: Access, user_id: str) -> User:
        """The user whose password the caller may set."""
        access.require("set_password")
        user = self._users.get(user_id)
        self._require_covers_user(access, user)
        if user_id == access.user_id:
            raise ConflictError("change your own password with the current one")
        if not user.ui_sign_in:
            raise ConflictError(
                f"{user.name} is an API user: switch on its UI sign-in first"
            )
        return user

    # --- tokens ---------------------------------------------------------------

    def list_tokens(self, access: Access, user_id: str) -> list[ApiToken]:
        access.require("list_tokens")
        self._require_covers_user(access, self._users.get(user_id))
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
        name = _named("a token", name)
        owner = self._users.get(user_id)
        self._require_covers_user(access, owner)
        token, plain = self._auth.issue_token(user_id, name, expires_at)
        self._activity.record(
            said.TokenIssued(
                by=Actor.of(access),
                token_id=token.id,
                token_name=token.name,
                user=owner,
                expires_at=token.expires_at,
            )
        )
        return token, plain

    def revoke_token(self, access: Access, user_id: str, token_id: str) -> ApiToken:
        access.require("revoke_token")
        owner = self._users.get(user_id)
        self._require_covers_user(access, owner)
        before = self._tokens.get(token_id)
        if before.user_id != user_id:
            raise missing("token", token_id)
        token = self._auth.revoke_token(token_id)
        if before.revoked_at is None:
            self._activity.record(
                said.TokenRevoked(
                    by=Actor.of(access),
                    token_id=token.id,
                    token_name=token.name,
                    user=owner,
                )
            )
        return token

    # --- roles ----------------------------------------------------------------

    def list_roles(self, access: Access) -> list[Role]:
        access.require("list_roles")
        return self._roles.list()

    def get_role(self, access: Access, role_id: str) -> Role:
        access.require("get_role")
        return self._roles.get(role_id)

    def create_role(self, access: Access, role_id: str, grants: list[Grant]) -> Role:
        access.require("create_role")
        role_id = _named("a role", role_id)
        if role_id in {role.id for role in self._roles.list()}:
            raise ConflictError(f"role {role_id} exists")
        role = self._save_role(access, Role(id=role_id, grants=grants))
        self._activity.record(
            said.RoleCreated(by=Actor.of(access), role_id=role.id, grants=len(grants))
        )
        return role

    def replace_role(self, access: Access, role_id: str, grants: list[Grant]) -> Role:
        """The role's holders change with it: the caller must be able to
        manage each of them, as for a change to the user itself."""
        access.require("replace_role")
        self._require_covers(access, self._roles.get(role_id).grants)
        for holder in self._holders(role_id):
            self._require_covers_user(access, holder)
        role = self._save_role(access, Role(id=role_id, grants=grants))
        self._activity.record(
            said.RoleReplaced(by=Actor.of(access), role_id=role.id, grants=len(grants))
        )
        return role

    def delete_role(self, access: Access, role_id: str) -> None:
        access.require("delete_role")
        role = self._roles.get(role_id)
        self._require_covers(access, role.grants)
        users = [user.id for user in self._holders(role_id)]
        if users:
            raise ConflictError(f"role {role_id} is used by {', '.join(users)}")
        self._roles.delete(role_id)
        self._activity.record(said.RoleDeleted(by=Actor.of(access), role_id=role_id))

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
        self,
        access: Access,
        role_ids: list[str],
        grants: list[Grant],
        new: list[Grant] | None = None,
    ) -> None:
        """The caller covers ``grants`` and the roles. ``new``, the grants
        given now, all of them unless said, name known rights."""
        _validate(grants if new is None else new)
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


def _named(what: str, name: str) -> str:
    """The name as it is kept: without the spaces around it."""
    name = name.strip()
    if not name:
        raise BadRequestError(f"{what} needs a name")
    if len(name) > MAX_NAME:
        raise BadRequestError(f"the name of {what} has {MAX_NAME} characters at most")
    return name


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
