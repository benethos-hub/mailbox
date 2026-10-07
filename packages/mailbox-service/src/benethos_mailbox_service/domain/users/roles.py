"""Roles: named sets of rights that users hold. A change to a role
changes each of its holders, so the caller must be able to manage them
all."""

from __future__ import annotations

from ...data.models import Grant, Role, User
from ...data.storage import RoleRepository
from ...errors import ConflictError
from ..activity import ActivityLog, Actor
from ..activity import users as said
from ..rights import Access
from .rules import UserRules, named, require_covers, validate


class RoleService:
    def __init__(
        self, roles: RoleRepository, rules: UserRules, activity: ActivityLog
    ) -> None:
        self._roles = roles
        self._rules = rules
        self._activity = activity

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
        role_id = named("a role", role_id)
        if role_id in {role.id for role in self._roles.list()}:
            raise ConflictError(f"role {role_id} exists")
        with self._activity.atomic():
            role = self._save(
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
        require_covers(access, before.grants, before.service)
        for holder in self._rules.holders(role_id):
            self._rules.require_covers_user(access, holder)
        new = Role(id=role_id, service=service or [], grants=grants)
        self._rules.require_an_administrator(role=new)
        with self._activity.atomic():
            role = self._save(access, new)
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
        require_covers(access, role.grants, role.service)
        users = [user.id for user in self._rules.holders(role_id)]
        if users:
            raise ConflictError(f"role {role_id} is used by {', '.join(users)}")
        with self._activity.atomic():
            self._roles.delete(role_id)
            self._activity.record(
                said.RoleDeleted(by=Actor.of(access), role_id=role_id)
            )

    def holders_of(self, access: Access, role_id: str) -> list[User]:
        """The users that hold a role."""
        access.require("list_users")
        self._roles.get(role_id)
        return self._rules.holders(role_id)

    def _save(self, access: Access, role: Role) -> Role:
        validate(role.grants, role.service)
        require_covers(access, role.grants, role.service)
        self._roles.save(role)
        return role
