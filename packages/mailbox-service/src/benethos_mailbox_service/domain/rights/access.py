"""What one caller may do: the effective rights of a user.

Built from the user's direct grants and the grants of its roles. Every
domain service asks an ``Access`` before it acts, so the JSON API and the
configuration UI share one check.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass

from ...data.models import Grant, Role, User
from ...errors import ForbiddenError, missing
from . import permissions

log = logging.getLogger(__name__)

ALL_ACCOUNTS = "*"
ANY_RECIPIENT = "*"
SEND_OPERATIONS = frozenset(permissions.GROUPS["send"])
# Every right on every account: what the first user gets.
ADMIN_GRANT = Grant(accounts=[ALL_ACCOUNTS], allow=[permissions.ADMIN])


@dataclass(frozen=True)
class SendLimit:
    """What one grant allows when sending: to whom and how often."""

    recipients: tuple[str, ...] | None  # None: to anyone
    max_per_day: int | None  # None: no limit

    def accepts(self, address: str) -> bool:
        return self.recipients is None or any(
            recipient_matches(pattern, address) for pattern in self.recipients
        )

    def within(self, other: SendLimit) -> bool:
        """Whether this is at most as wide as ``other``."""
        if other.recipients is not None and (
            self.recipients is None
            or not all(
                any(pattern_covers(outer, inner) for outer in other.recipients)
                for inner in self.recipients
            )
        ):
            return False
        return other.max_per_day is None or (
            self.max_per_day is not None and self.max_per_day <= other.max_per_day
        )


@dataclass(frozen=True)
class _Rule:
    accounts: frozenset[str] | None  # None means every account, "*"
    operations: frozenset[str]
    limit: SendLimit


class Access:
    def __init__(
        self,
        user_id: str,
        name: str,
        grants: Iterable[Grant],
        credential_id: str | None = None,
        roles: Iterable[str] = (),
        *,
        credential_name: str | None = None,
        source: str | None = None,
    ) -> None:
        self.user_id = user_id
        self.name = name
        # The token the caller presented, None for a session of the UI.
        self.credential_id = credential_id
        self.credential_name = credential_name
        # The client address of the request, for the log. None for work
        # the service does itself.
        self.source = source
        # The roles whose grants are among ``grants``, to show them.
        self.roles = tuple(roles)
        self._rules = tuple(_rule(grant) for grant in grants)

    @classmethod
    def for_user(
        cls,
        user: User,
        roles: Mapping[str, Role],
        credential_id: str | None = None,
        *,
        credential_name: str | None = None,
        source: str | None = None,
    ) -> Access:
        grants = list(user.grants)
        for role_id in user.roles:
            role = roles.get(role_id)
            if role is not None:
                grants.extend(role.grants)
        return cls(
            user.id,
            user.name,
            grants,
            credential_id,
            user.roles,
            credential_name=credential_name,
            source=source,
        )

    @classmethod
    def admin(cls, user_id: str, name: str) -> Access:
        return cls(user_id, name, [ADMIN_GRANT])

    def is_admin(self) -> bool:
        """Whether the caller holds ``admin``: the rights only it gives."""
        return all(self.allows(op) for op in permissions.ADMIN_ONLY)

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

    def filter(self, operation: str, account_ids: Iterable[str]) -> list[str]:
        """The accounts of ``account_ids`` the operation is allowed on, each
        once, in their order."""
        return [a for a in dict.fromkeys(account_ids) if self.allows(operation, a)]

    def sees(self, account_id: str) -> bool:
        """Whether the account exists for this caller at all: some right on
        it that is about existing accounts."""
        return any(
            rule.operations - permissions.NOT_ON_AN_ACCOUNT
            for rule in self._on(account_id)
        )

    def anywhere(self, operation: str) -> bool:
        """Whether the operation is allowed on at least one account, or
        without one."""
        return self.allows(operation) or any(
            operation in rule.operations
            and operation not in permissions.ALL_ACCOUNTS
            and (rule.accounts is None or bool(rule.accounts))
            for rule in self._rules
        )

    def sees_status(self) -> bool:
        """The status of the service is for callers who may list some
        account."""
        return self.anywhere("list_accounts")

    def batches(self, operation: str, account_id: str) -> bool:
        """Whether a batch of ``operation`` is allowed on the account: the
        right to batch and the operation itself, as a batch checks them."""
        return self.allows("batch_messages", account_id) and self.allows(
            operation, account_id
        )

    def require(self, operation: str, account_id: str | None = None) -> None:
        """Raise unless allowed: ``NotFoundError`` for an account this caller
        cannot see, ``ForbiddenError`` for a missing right."""
        if self.allows(operation, account_id):
            return
        if account_id is not None and not self.sees(account_id):
            raise missing("account", account_id)
        where = f" on account {account_id}" if account_id else ""
        raise ForbiddenError(f"missing right: {operation}{where}")

    def send_limits(self, operation: str, account_id: str) -> list[SendLimit]:
        """The limits of every grant that allows ``operation`` on the
        account. A send is allowed when one of them allows it."""
        return [
            rule.limit for rule in self._on(account_id) if operation in rule.operations
        ]

    def sending_limits(self, account_id: str) -> list[SendLimit]:
        """The limits of every grant that allows any kind of sending on the
        account, each grant once."""
        return [
            rule.limit
            for rule in self._on(account_id)
            if rule.operations & SEND_OPERATIONS
        ]

    def sends_anywhere(self, account_id: str) -> bool:
        """Whether a grant lets the caller send from the account to any
        address, however often."""
        return any(
            limit.recipients is None for limit in self.sending_limits(account_id)
        )

    def covers(self, grants: Iterable[Grant]) -> bool:
        """Whether every right in ``grants`` is one this caller holds itself,
        sending no wider than its own grants allow. A name that is no right
        (any more) grants nothing and asks for nothing: new grants are
        checked for such names before."""
        for grant in grants:
            rule = _rule(grant)
            for operation in rule.operations:
                if operation in permissions.ACCOUNT_FREE:
                    if not self.allows(operation):
                        return False
                elif ALL_ACCOUNTS in grant.accounts:
                    if not self._allows_everywhere(operation, rule.limit):
                        return False
                elif operation in permissions.ALL_ACCOUNTS:
                    # Such as create_account: a grant on named accounts
                    # grants it nowhere, so it asks for nothing.
                    continue
                elif not all(
                    self._allows_within(operation, a, rule.limit)
                    for a in grant.accounts
                ):
                    return False
        return True

    def _allows_within(self, operation: str, account_id: str, limit: SendLimit) -> bool:
        if operation not in SEND_OPERATIONS:
            return self.allows(operation, account_id)
        return any(limit.within(own) for own in self.send_limits(operation, account_id))

    def operations_on(self, account_id: str) -> frozenset[str]:
        """Every account-bound operation allowed on one account."""
        return frozenset(
            op for op in permissions.ON_AN_ACCOUNT if self.allows(op, account_id)
        )

    def general_operations(self) -> frozenset[str]:
        """Operations not bound to one existing account."""
        return frozenset(op for op in permissions.NOT_ON_AN_ACCOUNT if self.allows(op))

    def _allows_everywhere(self, operation: str, limit: SendLimit) -> bool:
        return any(
            operation in rule.operations
            and (operation not in SEND_OPERATIONS or limit.within(rule.limit))
            for rule in self._on(None)
        )

    def _on(self, account_id: str | None) -> Iterator[_Rule]:
        """The rules that reach the account. None: those on every account."""
        return (
            rule
            for rule in self._rules
            if rule.accounts is None
            or (account_id is not None and account_id in rule.accounts)
        )


def _rule(grant: Grant) -> _Rule:
    accounts = None if ALL_ACCOUNTS in grant.accounts else frozenset(grant.accounts)
    recipients = None if grant.recipients is None else tuple(grant.recipients)
    if recipients is not None and ANY_RECIPIENT in recipients:
        recipients = None
    operations, unknown = permissions.expand_known(grant.allow)
    if unknown:
        log.warning("a stored grant names rights that do not exist: %s", unknown)
    return _Rule(accounts, operations, SendLimit(recipients, grant.max_sends_per_day))


def recipient_matches(pattern: str, address: str) -> bool:
    """An address against ``*``, ``*@domain`` or an address, ignoring case.
    A local part with ``%`` or ``!`` matches no domain: some servers route
    ``bob%evil.org@domain`` on to evil.org. Only its exact address does."""
    pattern, address = pattern.casefold(), address.casefold()
    if pattern == ANY_RECIPIENT:
        return True
    if pattern.startswith("*@"):
        local, _, domain = address.rpartition("@")
        return domain == pattern[2:] and not any(c in local for c in _ROUTING)
    return address == pattern


# Characters of source routing in a local part (RFC 1123 5.2.16, UUCP).
_ROUTING = "%!"


def pattern_covers(outer: str, inner: str) -> bool:
    """Whether every address ``inner`` matches is one ``outer`` matches."""
    if inner.casefold() == ANY_RECIPIENT:
        return outer == ANY_RECIPIENT
    if inner.startswith("*@"):
        return outer == ANY_RECIPIENT or outer.casefold() == inner.casefold()
    return recipient_matches(outer, inner)
