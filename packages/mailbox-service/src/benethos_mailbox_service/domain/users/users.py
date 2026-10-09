"""Users: made, read, changed and deleted within the caller's rights,
and what each may do in effect. The rules every change keeps are in
``rules``."""

from __future__ import annotations

from dataclasses import dataclass

from ...common.secret import new_id
from ...data.models import Grant, Page, User
from ...data.storage import (
    RoleRepository,
    TokenRepository,
    UserRepository,
    WebhookRepository,
)
from ...errors import BadRequestError, ConflictError, MailboxServiceError, NotFoundError
from .. import paging
from ..activity import HOST, ActivityLog, Actor
from ..activity import users as said
from ..auth import AuthService
from ..rights import ADMIN_SERVICE, Access, permissions
from .effective import Effective, EffectiveRights
from .passwords import PasswordService
from .rules import UserRules, named

BY_NAME = paging.Order[User]("u_", lambda u: (u.name.casefold(), u.id))

# What a batch of the users list does to each ticked user.
BATCH_ACTIONS = ("disable", "enable", "give_role", "take_role")


@dataclass(frozen=True)
class BatchOutcome:
    """What a batch did: the users it changed, and for each one it could
    not change, its name and why. A user that was as asked already is in
    neither."""

    changed: list[User]
    refused: list[tuple[str, str]]


class UserService:
    def __init__(
        self,
        users: UserRepository,
        roles: RoleRepository,
        tokens: TokenRepository,
        webhooks: WebhookRepository,
        auth: AuthService,
        passwords: PasswordService,
        effective: Effective,
        rules: UserRules,
        activity: ActivityLog,
    ) -> None:
        self._users = users
        self._roles = roles
        self._tokens = tokens
        self._webhooks = webhooks
        self._auth = auth
        self._passwords = passwords
        self._effective = effective
        self._rules = rules
        self._activity = activity

    # --- what a user may do ---------------------------------------------------

    def me(self, access: Access) -> EffectiveRights:
        return self._effective.rights(access, visible_to=None, roles=list(access.roles))

    def rights_of(self, access: Access, user_id: str) -> EffectiveRights:
        """What a user may do, its direct grants and those of its roles
        together. Only accounts the caller can see are listed."""
        access.require("get_user")
        user = self._users.get(user_id)
        roles = {role.id: role for role in self._roles.list()}
        return self._effective.rights(
            Access.for_user(user, roles), visible_to=access, roles=user.roles
        )

    # --- setup ----------------------------------------------------------------

    async def create_admin(self, name: str) -> tuple[User, str]:
        """A user with every right, and a one-time password for it, to be
        changed at the first sign-in. For the command line on the host
        only: it checks no caller."""
        name = named("a user", name)
        self._require_free(name)
        user = User(
            id=new_id("usr"),
            name=name,
            service=list(ADMIN_SERVICE),
            ui_sign_in=True,
        )
        with self._activity.atomic():
            self._users.save(user)
            self._activity.record(said.UserCreated(by=HOST, user=user))
        return user, await self._passwords.one_time(user)

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
        name = named("a user", name)
        self._require_free(name)
        user = User(
            id=new_id("usr"),
            name=name,
            roles=roles,
            service=service or [],
            grants=grants,
            ui_sign_in=ui_sign_in,
        )
        self._rules.check_grantable(access, user)
        with self._activity.atomic():
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
        """Switching ``ui_sign_in`` off deletes the password and the second
        factor, which ends the user's UI sessions. Nobody disables itself
        or takes its own UI sign-in."""
        user = self._rules.managed(access, "update_user", user_id)
        if name is not None:
            name = named("a user", name)
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
        self._rules.check_grantable(access, updated, grants or [], service or [])
        self._rules.require_an_administrator(replaced=updated)
        changed = tuple(
            key for key in changes if getattr(user, key) != getattr(updated, key)
        )
        with self._activity.atomic():
            self._users.save(updated)
            if changed:
                self._activity.record(
                    said.UserChanged(by=Actor.of(access), user=updated, changed=changed)
                )
            if user.ui_sign_in and not updated.ui_sign_in:
                self._auth.passwords.delete(user_id)
                self._remove_factor(user_id)
                self._activity.record(said.MadeApiUser(by=Actor.of(access), user=user))
        return updated

    def change_users(
        self,
        access: Access,
        user_ids: list[str],
        action: str,
        role: str | None = None,
    ) -> BatchOutcome:
        """One change to each of several users, as ``update_user`` makes
        it: within the caller's rights, recorded per user. A user it cannot
        change is named with the reason, the others are changed still.
        ``action`` is one of ``BATCH_ACTIONS``, the role ones with
        ``role``."""
        if action not in BATCH_ACTIONS:
            raise BadRequestError(f"no such change of users: {action}")
        if action in ("give_role", "take_role") and not role:
            raise BadRequestError("choose a role")
        if not user_ids:
            raise BadRequestError("tick at least one user")
        changed, refused = [], []
        for user_id in dict.fromkeys(user_ids):
            try:
                done = self._change_one(access, user_id, action, role or "")
            except MailboxServiceError as exc:
                refused.append((self._name_of(user_id), exc.message))
            else:
                if done is not None:
                    changed.append(done)
        return BatchOutcome(changed=changed, refused=refused)

    def _change_one(
        self, access: Access, user_id: str, action: str, role: str
    ) -> User | None:
        """The user changed, None when it was as asked already."""
        user = self._rules.managed(access, "update_user", user_id)
        if action in ("disable", "enable"):
            disabled = action == "disable"
            if user.disabled == disabled:
                return None
            return self.update_user(access, user_id, disabled=disabled)
        roles = [r for r in user.roles if r != role]
        if action == "give_role":
            roles.append(role)
        if sorted(roles) == sorted(user.roles):
            return None
        return self.update_user(access, user_id, roles=roles)

    def _name_of(self, user_id: str) -> str:
        try:
            return self._users.get(user_id).name
        except NotFoundError:
            return user_id

    def delete_user(self, access: Access, user_id: str) -> None:
        user = self._rules.managed(access, "delete_user", user_id)
        if user_id == access.user_id:
            raise ConflictError("a user cannot delete itself")
        self._rules.require_an_administrator(deleted=user_id)
        with self._activity.atomic():
            self._tokens.delete_for_user(user_id)
            self._auth.passwords.delete(user_id)
            self._remove_factor(user_id)
            # Its webhooks would post by nobody's rights, and nobody could
            # remove them.
            removed = self._webhooks.delete_for_user(user_id)
            self._users.delete(user_id)
            self._activity.record(
                said.UserDeleted(by=Actor.of(access), user=user, webhooks=removed)
            )

    def _remove_factor(self, user_id: str) -> None:
        """The second factor goes with the password."""
        if self._auth.factors is not None:
            self._auth.factors.remove(user_id)

    def _require_free(self, name: str, user_id: str | None = None) -> None:
        """A person signs in with the name: one user per name, whatever
        the case."""
        taken = self._auth.user_named(name)
        if taken is not None and taken.id != user_id:
            raise ConflictError(f"a user named {taken.name} exists")

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
        with self._activity.atomic():
            self._users.save(updated)
            self._activity.record(
                said.UserChanged(by=Actor.of(access), user=updated, changed=("grants",))
            )
