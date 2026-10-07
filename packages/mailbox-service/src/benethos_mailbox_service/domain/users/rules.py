"""What every change to users and roles keeps (PERMISSIONS.md).

No escalation: a caller can only hand out rights it holds itself, and can
only manage a user whose rights it holds itself. A change never leaves
the service without an enabled administrator who can sign in to the UI.
"""

from __future__ import annotations

from collections.abc import Iterable

from ...data.models import Grant, Role, User
from ...data.storage import RoleRepository, UserRepository
from ...errors import BadRequestError, ConflictError, ForbiddenError, NotFoundError
from ..auth import MAX_NAME
from ..rights import Access, permissions


class UserRules:
    """The rules, over the users and roles stored now."""

    def __init__(self, users: UserRepository, roles: RoleRepository) -> None:
        self._users = users
        self._roles = roles

    def managed(self, access: Access, operation: str, user_id: str) -> User:
        """The user the caller does ``operation`` on: with the right to it,
        and holding every right the user has."""
        access.require(operation)
        user = self._users.get(user_id)
        self.require_covers_user(access, user)
        return user

    def require_covers_user(self, access: Access, user: User) -> None:
        roles = [role for role in user.roles if self._exists(role)]
        grants, service = self.role_rights(roles)
        require_covers(access, [*user.grants, *grants], [*user.service, *service])

    def check_grantable(
        self,
        access: Access,
        user: User,
        grants: list[Grant] | None = None,
        service: list[str] | None = None,
    ) -> None:
        """The caller covers the user's rights and roles. ``grants`` and
        ``service``, the rights given now, all of them unless said, name
        known rights of the right kind."""
        validate(
            user.grants if grants is None else grants,
            user.service if service is None else service,
        )
        role_grants, role_service = self.role_rights(user.roles)
        require_covers(
            access, [*user.grants, *role_grants], [*user.service, *role_service]
        )

    def require_an_administrator(
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

    def role_rights(self, role_ids: Iterable[str]) -> tuple[list[Grant], list[str]]:
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

    def holders(self, role_id: str) -> list[User]:
        """The users that hold a role."""
        return [user for user in self._users.list() if role_id in user.roles]

    def _exists(self, role_id: str) -> bool:
        try:
            self._roles.get(role_id)
        except NotFoundError:
            return False
        return True


def require_covers(
    access: Access, grants: list[Grant], service: Iterable[str] = ()
) -> None:
    if not access.covers(grants, service):
        raise ForbiddenError("cannot grant or manage rights the caller lacks")


def named(what: str, name: str) -> str:
    """The name as it is kept: without the spaces around it."""
    name = name.strip()
    if not name:
        raise BadRequestError(f"{what} needs a name")
    if len(name) > MAX_NAME:
        raise BadRequestError(f"the name of {what} has {MAX_NAME} characters at most")
    return name


def validate(grants: Iterable[Grant], service: Iterable[str]) -> None:
    """Rights on accounts in grants, rights of the service in ``service``:
    a name in the wrong place answers 400, it is never moved silently."""
    permissions.check_service(service)
    for grant in grants:
        if not grant.accounts:
            raise BadRequestError("a grant needs at least one account or '*'")
        permissions.check_grant(grant.allow)


def _administrators(users: Iterable[User], roles: dict[str, Role]) -> list[str]:
    """The enabled users with ``admin`` who may sign in to the UI."""
    return [
        user.id
        for user in users
        if not user.disabled
        and user.ui_sign_in
        and Access.for_user(user, roles).is_admin()
    ]
