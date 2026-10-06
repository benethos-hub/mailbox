"""Users, their tokens, passwords and roles.

No escalation: a caller can only hand out rights it holds itself, and can
only manage a user whose rights it holds itself.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime

from ...common.ids import new_id
from ...data.models import (
    AccountStatus,
    ApiToken,
    Capability,
    Grant,
    Page,
    Role,
    User,
)
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
from .. import paging
from ..accounts import Adapters
from ..activity import HOST, ActivityLog, Actor
from ..activity import users as said
from ..auth import MAX_NAME, AuthService, SignInState, TokenState
from ..rights import ADMIN_SERVICE, Access, permissions

# A one-time password of 18 random bytes: 24 characters, 144 bits.
ONE_TIME_BYTES = 18

BY_NAME = paging.Order[User]("u_", lambda u: (u.name.casefold(), u.id))


@dataclass(frozen=True)
class Sending:
    """One grant that allows sending from an account: to whom, how many in
    24 hours, and how many of those are left now (PERMISSIONS.md 8.8)."""

    recipients: list[str] | None  # None: to anyone
    max_sends_per_day: int | None  # None: no limit
    sends_left: int | None  # None: no limit


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
    sending: list[Sending]
    status: AccountStatus = AccountStatus.CONNECTED
    capabilities: list[Capability] = field(default_factory=list)


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
        sent: Callable[[str, str], int] | None = None,
    ) -> None:
        """``sent``: how many mails a user sent from an account in the last
        24 hours, by user and account id."""
        self._users = users
        self._sent = sent
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
                        sending=self._sending(access, account_id),
                        status=account.status,
                        capabilities=self._adapters.offered(account_id),
                    )
                )
        return EffectiveRights(
            user_id=access.user_id,
            name=access.name,
            accounts=accounts,
            operations=sorted(access.general_operations()),
            roles=list(roles),
        )

    def _sending(self, access: Access, account_id: str) -> list[Sending]:
        limits = access.sending_limits(account_id)
        sent = (
            self._sent(access.user_id, account_id)
            if self._sent is not None and any(x.max_per_day for x in limits)
            else 0
        )
        return [
            Sending(
                recipients=list(limit.recipients)
                if limit.recipients is not None
                else None,
                max_sends_per_day=limit.max_per_day,
                sends_left=max(0, limit.max_per_day - sent)
                if limit.max_per_day is not None
                else None,
            )
            for limit in limits
        ]

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
            service=list(ADMIN_SERVICE),
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

    def page_users(
        self,
        access: Access,
        *,
        limit: int,
        cursor: str | None = None,
        name: str | None = None,
        role: str | None = None,
        disabled: bool | None = None,
        ui_sign_in: bool | None = None,
    ) -> Page[User]:
        """A page of ``list_users``, by name regardless of case."""
        found = self.list_users(
            access, name=name, role=role, disabled=disabled, ui_sign_in=ui_sign_in
        )
        return paging.page(found, BY_NAME, limit=limit, cursor=cursor)

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
        service: list[str] | None = None,
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
            service=service or [],
            grants=grants,
            ui_sign_in=ui_sign_in,
        )
        self._check_grantable(access, user)
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
        service: list[str] | None = None,
        grants: list[Grant] | None = None,
        disabled: bool | None = None,
        ui_sign_in: bool | None = None,
    ) -> User:
        """Switching ``ui_sign_in`` off deletes the password, which ends the
        user's UI sessions. Nobody disables itself or takes its own UI
        sign-in."""
        user = self._managed(access, "update_user", user_id)
        if name is not None:
            name = _named("a user", name)
            self._require_free(name, user_id)
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
                "service": service,
                "grants": grants,
                "disabled": disabled,
                "ui_sign_in": ui_sign_in,
            }.items()
            if value is not None
        }
        updated = user.model_copy(update=changes)
        # Only rights given now must be known. A stored one may name a
        # right a release renamed, and grants nothing by it.
        self._check_grantable(access, updated, grants or [], service or [])
        self._require_an_administrator(replaced=updated)
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
        user = self._managed(access, "delete_user", user_id)
        if user_id == access.user_id:
            raise ConflictError("a user cannot delete itself")
        self._require_an_administrator(deleted=user_id)
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

    def sign_in_state(self, user: User) -> SignInState:
        """Whether the user has a password, must change it, and when it
        last signed in to the UI. For a user the caller has read already,
        as ``token_state`` is for a token."""
        return self._auth.sign_in_state(user.id)

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
        user = self._managed(access, "set_password", user_id)
        if user_id == access.user_id:
            raise ConflictError("change your own password with the current one")
        if not user.ui_sign_in:
            raise ConflictError(
                f"{user.name} is an API user: switch on its UI sign-in first"
            )
        return user

    # --- tokens ---------------------------------------------------------------

    def list_tokens(self, access: Access, user_id: str) -> list[ApiToken]:
        self._managed(access, "list_tokens", user_id)
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
        owner = self._managed(access, "create_token", user_id)
        name = _named("a token", name)
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
        owner = self._managed(access, "revoke_token", user_id)
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

    def create_role(
        self,
        access: Access,
        role_id: str,
        grants: list[Grant],
        service: list[str] | None = None,
    ) -> Role:
        access.require("create_role")
        role_id = _named("a role", role_id)
        if role_id in {role.id for role in self._roles.list()}:
            raise ConflictError(f"role {role_id} exists")
        role = self._save_role(
            access, Role(id=role_id, service=service or [], grants=grants)
        )
        self._activity.record(
            said.RoleCreated(
                by=Actor.of(access),
                role_id=role.id,
                service=tuple(role.service),
                grants=len(grants),
            )
        )
        return role

    def replace_role(
        self,
        access: Access,
        role_id: str,
        grants: list[Grant],
        service: list[str] | None = None,
    ) -> Role:
        """The role's holders change with it: the caller must be able to
        manage each of them, as for a change to the user itself."""
        access.require("replace_role")
        before = self._roles.get(role_id)
        self._require_covers(access, before.grants, before.service)
        for holder in self._holders(role_id):
            self._require_covers_user(access, holder)
        new = Role(id=role_id, service=service or [], grants=grants)
        self._require_an_administrator(role=new)
        role = self._save_role(access, new)
        self._activity.record(
            said.RoleReplaced(
                by=Actor.of(access),
                role_id=role.id,
                service=tuple(role.service),
                grants=len(grants),
            )
        )
        return role

    def delete_role(self, access: Access, role_id: str) -> None:
        access.require("delete_role")
        role = self._roles.get(role_id)
        self._require_covers(access, role.grants, role.service)
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

    # --- an account connected ------------------------------------------------

    def connected(self, access: Access, account_id: str) -> None:
        """Whoever connects an account gets ``accounts.manage`` on it, so
        it can verify and remove what it connected (PERMISSIONS.md 8.1).
        Nothing for a caller that holds it there already, nor for one that
        is no stored user."""
        manage = permissions.GROUPS["accounts.manage"]
        if all(access.allows(op, account_id) for op in manage):
            return
        try:
            user = self._users.get(access.user_id)
        except NotFoundError:
            return
        grant = Grant(accounts=[account_id], allow=["accounts.manage"])
        updated = user.model_copy(update={"grants": [*user.grants, grant]})
        self._users.save(updated)
        self._activity.record(
            said.UserChanged(by=Actor.of(access), user=updated, changed=("grants",))
        )

    def _save_role(self, access: Access, role: Role) -> Role:
        _validate(role.grants, role.service)
        self._require_covers(access, role.grants, role.service)
        self._roles.save(role)
        return role

    def _check_grantable(
        self,
        access: Access,
        user: User,
        grants: list[Grant] | None = None,
        service: list[str] | None = None,
    ) -> None:
        """The caller covers the user's rights and roles. ``grants`` and
        ``service``, the rights given now, all of them unless said, name
        known rights of the right kind."""
        _validate(
            user.grants if grants is None else grants,
            user.service if service is None else service,
        )
        role_grants, role_service = self._role_rights(user.roles)
        self._require_covers(
            access, [*user.grants, *role_grants], [*user.service, *role_service]
        )

    def _require_an_administrator(
        self,
        *,
        replaced: User | None = None,
        deleted: str | None = None,
        role: Role | None = None,
    ) -> None:
        """Refuse a change that would leave no enabled administrator who
        can sign in to the UI, where there was one (PERMISSIONS.md 8.3).
        The way back would be the host's ``users set-password`` alone."""
        users = self._users.list()
        roles = {r.id: r for r in self._roles.list()}
        if not _administrators(users, roles):
            return
        after = [
            replaced if replaced is not None and u.id == replaced.id else u
            for u in users
            if u.id != deleted
        ]
        if role is not None:
            roles = {**roles, role.id: role}
        if not _administrators(after, roles):
            raise ConflictError(
                "no enabled administrator who can sign in to the UI would be left"
            )

    def _role_rights(self, role_ids: Iterable[str]) -> tuple[list[Grant], list[str]]:
        """The grants and the service rights of the roles together."""
        grants: list[Grant] = []
        service: list[str] = []
        for role_id in role_ids:
            try:
                role = self._roles.get(role_id)
            except NotFoundError:
                raise BadRequestError(f"unknown role: {role_id}") from None
            grants.extend(role.grants)
            service.extend(role.service)
        return grants, service

    def _managed(self, access: Access, operation: str, user_id: str) -> User:
        """The user the caller does ``operation`` on: with the right to it,
        and holding every right the user has."""
        access.require(operation)
        user = self._users.get(user_id)
        self._require_covers_user(access, user)
        return user

    def _require_covers_user(self, access: Access, user: User) -> None:
        roles = [role for role in user.roles if _exists(self._roles, role)]
        grants, service = self._role_rights(roles)
        self._require_covers(access, [*user.grants, *grants], [*user.service, *service])

    @staticmethod
    def _require_covers(
        access: Access, grants: list[Grant], service: Iterable[str] = ()
    ) -> None:
        if not access.covers(grants, service):
            raise ForbiddenError("cannot grant or manage rights the caller lacks")


def _administrators(users: Iterable[User], roles: dict[str, Role]) -> list[str]:
    """The enabled users with ``admin`` who may sign in to the UI."""
    return [
        user.id
        for user in users
        if not user.disabled
        and user.ui_sign_in
        and Access.for_user(user, roles).is_admin()
    ]


def _named(what: str, name: str) -> str:
    """The name as it is kept: without the spaces around it."""
    name = name.strip()
    if not name:
        raise BadRequestError(f"{what} needs a name")
    if len(name) > MAX_NAME:
        raise BadRequestError(f"the name of {what} has {MAX_NAME} characters at most")
    return name


def _validate(grants: Iterable[Grant], service: Iterable[str]) -> None:
    """Rights on accounts in grants, rights of the service in ``service``:
    a name in the wrong place answers 400, it is never moved silently."""
    permissions.check_service(service)
    for grant in grants:
        if not grant.accounts:
            raise BadRequestError("a grant needs at least one account or '*'")
        permissions.check_grant(grant.allow)


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
