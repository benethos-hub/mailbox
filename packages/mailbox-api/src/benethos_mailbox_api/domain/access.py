"""What one caller may do: the effective rights of a user.

Built from the user's direct grants and the grants of its roles. Every
domain service asks an ``Access`` before it acts, so the JSON API and the
configuration UI share one check.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from ..data.models import Grant, Role, User
from ..errors import ForbiddenError, NotFoundError
from . import permissions

ALL_ACCOUNTS = "*"


@dataclass(frozen=True)
class _Rule:
    accounts: frozenset[str] | None  # None means every account, "*"
    operations: frozenset[str]


class Access:
    def __init__(self, user_id: str, name: str, grants: Iterable[Grant]) -> None:
        self.user_id = user_id
        self.name = name
        self._rules = tuple(_rule(grant) for grant in grants)

    @classmethod
    def for_user(cls, user: User, roles: Mapping[str, Role]) -> Access:
        grants = list(user.grants)
        for role_id in user.roles:
            role = roles.get(role_id)
            if role is not None:
                grants.extend(role.grants)
        return cls(user.id, user.name, grants)

    @classmethod
    def admin(cls, user_id: str, name: str) -> Access:
        return cls(
            user_id, name, [Grant(accounts=[ALL_ACCOUNTS], allow=[permissions.ADMIN])]
        )

    def allows(self, operation: str, account_id: str | None = None) -> bool:
        if operation in permissions.AUTHENTICATED_OPERATIONS:
            return True
        for rule in self._rules:
            if operation not in rule.operations:
                continue
            if operation in permissions.ACCOUNT_FREE:
                return True
            if operation in permissions.ALL_ACCOUNTS:
                if rule.accounts is None:
                    return True
                continue
            if account_id is not None and (
                rule.accounts is None or account_id in rule.accounts
            ):
                return True
        return False

    def sees(self, account_id: str) -> bool:
        """Whether the account exists for this caller at all."""
        return any(
            (rule.accounts is None or account_id in rule.accounts)
            and rule.operations - permissions.ACCOUNT_FREE
            for rule in self._rules
        )

    def require(self, operation: str, account_id: str | None = None) -> None:
        """Raise unless allowed: ``NotFoundError`` for an account this caller
        cannot see, ``ForbiddenError`` for a missing right."""
        if self.allows(operation, account_id):
            return
        if account_id is not None and not self.sees(account_id):
            raise NotFoundError(f"account {account_id} not found")
        where = f" on account {account_id}" if account_id else ""
        raise ForbiddenError(f"missing right: {operation}{where}")

    def covers(self, grants: Iterable[Grant]) -> bool:
        """Whether every right in ``grants`` is one this caller holds itself."""
        for grant in grants:
            for operation in permissions.expand(grant.allow):
                if operation in permissions.ACCOUNT_FREE:
                    if not self.allows(operation):
                        return False
                elif ALL_ACCOUNTS in grant.accounts:
                    if not self._allows_everywhere(operation):
                        return False
                elif not all(self.allows(operation, a) for a in grant.accounts):
                    return False
        return True

    def operations_on(self, account_id: str) -> frozenset[str]:
        """Every account-bound operation allowed on one account."""
        return frozenset(
            op
            for op in permissions.GROUP_OF
            if op not in permissions.ACCOUNT_FREE
            and op not in permissions.ALL_ACCOUNTS
            and self.allows(op, account_id)
        )

    def general_operations(self) -> frozenset[str]:
        """Operations not bound to one existing account."""
        return frozenset(
            op
            for op in permissions.GROUP_OF
            if op in permissions.ACCOUNT_FREE or op in permissions.ALL_ACCOUNTS
            if self.allows(op)
        )

    def _allows_everywhere(self, operation: str) -> bool:
        return any(
            rule.accounts is None and operation in rule.operations
            for rule in self._rules
        )


def _rule(grant: Grant) -> _Rule:
    accounts = None if ALL_ACCOUNTS in grant.accounts else frozenset(grant.accounts)
    return _Rule(accounts, permissions.expand(grant.allow))
