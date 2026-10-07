"""What one caller may do: the effective rights of a user.

Built from the user's direct grants and service rights and those of its
roles. Every domain service asks an ``Access`` before it acts, so the
JSON API and the configuration UI share one check.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime

from ...common.clock import utc_now
from ...data.models import Grant, Role, User
from ...errors import ForbiddenError, missing
from . import permissions

ALL_ACCOUNTS = "*"
ANY_RECIPIENT = "*"
SEND_OPERATIONS = frozenset(permissions.GROUPS["send"])
# Every right: what the first user gets, in its service rights.
ADMIN_SERVICE = (permissions.ADMIN,)


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
    expires_at: datetime | None = None  # None: never
    folders: frozenset[str] | None = None  # None: every folder

    def within(self, own: _Rule, operation: str) -> bool:
        """Whether ``operation`` under this rule is at most as wide as
        under ``own``: sending as narrow, in no other folders, and ending
        no later."""
        if operation in SEND_OPERATIONS and not self.limit.within(own.limit):
            return False
        if (
            operation in permissions.IN_FOLDERS
            and own.folders is not None
            and (self.folders is None or not self.folders <= own.folders)
        ):
            return False
        return own.expires_at is None or (
            self.expires_at is not None and self.expires_at <= own.expires_at
        )


class Access:
    def __init__(
        self,
        user_id: str,
        name: str,
        grants: Iterable[Grant],
        credential_id: str | None = None,
        roles: Iterable[str] = (),
        *,
        service: Iterable[str] = (),
        credential_name: str | None = None,
        source: str | None = None,
        now: datetime | None = None,
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
        service = list(service)
        grants = list(grants)
        self._service = _service_operations(service)
        # Names in stored grants and service rights that are no right, e.g.
        # of an older version. They give nothing. Whoever builds the
        # access from stored records logs them.
        self.unknown = frozenset(
            name
            for names in (service, *(grant.allow for grant in grants))
            for name in permissions.expand_known(names)[1]
        )
        # A grant that has expired grants nothing (PERMISSIONS.md 8.4).
        self._now = now or utc_now()
        rules = [
            rule for grant in grants if not _expired(rule := _rule(grant), self._now)
        ]
        if permissions.ADMIN in service:
            # admin is every right: on every account as well.
            rules.append(_Rule(None, permissions.ON_AN_ACCOUNT, SendLimit(None, None)))
        self._rules = tuple(rules)

    @classmethod
    def for_user(
        cls,
        user: User,
        roles: Mapping[str, Role],
        credential_id: str | None = None,
        *,
        credential_name: str | None = None,
        source: str | None = None,
        now: datetime | None = None,
    ) -> Access:
        grants = list(user.grants)
        service = list(user.service)
        for role_id in user.roles:
            role = roles.get(role_id)
            if role is not None:
                grants.extend(role.grants)
                service.extend(role.service)
        return cls(
            user.id,
            user.name,
            grants,
            credential_id,
            user.roles,
            service=service,
            credential_name=credential_name,
            source=source,
            now=now,
        )

    def is_admin(self) -> bool:
        """Whether the caller holds ``admin``: the rights only it gives."""
        return all(self.allows(op) for op in permissions.ADMIN_ONLY)

    def allows(self, operation: str, account_id: str | None = None) -> bool:
        if operation in permissions.AUTHENTICATED_OPERATIONS:
            return True
        if operation in permissions.SERVICE:
            return operation in self._service
        return account_id is not None and any(
            operation in rule.operations for rule in self._on(account_id)
        )

    def filter(self, operation: str, account_ids: Iterable[str]) -> list[str]:
        """The accounts of ``account_ids`` the operation is allowed on, each
        once, in their order."""
        return [a for a in dict.fromkeys(account_ids) if self.allows(operation, a)]

    def sees(self, account_id: str) -> bool:
        """Whether the account exists for this caller at all: some right on
        it that is about existing accounts."""
        return any(rule.operations for rule in self._on(account_id))

    def anywhere(self, operation: str) -> bool:
        """Whether the operation is allowed on at least one account, or
        without one."""
        return self.allows(operation) or any(
            operation in rule.operations
            and (rule.accounts is None or bool(rule.accounts))
            for rule in self._rules
        )

    def sees_status(self) -> bool:
        """The status of the service is for callers who may see it of
        some account."""
        return self.anywhere("get_status")

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

    def folder_scopes(
        self, operation: str, account_id: str
    ) -> list[frozenset[str]] | None:
        """The folders of each grant that allows ``operation`` on the
        account (PERMISSIONS.md 8.5). None: some grant reaches every
        folder, or the operation is not about folders. A call passes when
        one grant reaches every folder it touches."""
        if operation not in permissions.IN_FOLDERS:
            return None
        scopes = []
        for rule in self._on(account_id):
            if operation in rule.operations:
                if rule.folders is None:
                    return None
                scopes.append(rule.folders)
        return scopes

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

    def covers(self, grants: Iterable[Grant], service: Iterable[str] = ()) -> bool:
        """Whether every right in ``grants`` and ``service`` is one this
        caller holds itself, sending no wider and ending no later than its
        own grants. A name that is no right (any more) grants nothing and
        asks for nothing, nor does a grant that has expired: new rights are
        checked for such names before."""
        service = list(service)
        if permissions.ADMIN in service and not self.is_admin():
            return False
        if not _service_operations(service) <= self._service:
            return False
        for grant in grants:
            rule = _rule(grant)
            if _expired(rule, self._now):
                continue
            places: list[str | None] = (
                [None] if ALL_ACCOUNTS in grant.accounts else list(grant.accounts)
            )
            for operation in rule.operations:
                for place in places:
                    if not any(
                        operation in own.operations and rule.within(own, operation)
                        for own in self._on(place)
                    ):
                        return False
        return True

    def operations_on(self, account_id: str) -> frozenset[str]:
        """Every account-bound operation allowed on one account."""
        return frozenset(
            op for op in permissions.ON_AN_ACCOUNT if self.allows(op, account_id)
        )

    def general_operations(self) -> frozenset[str]:
        """Operations of the service: bound to no existing account."""
        return self._service

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
    operations, _ = permissions.expand_known(grant.allow)
    # A grant gives rights on accounts alone, whatever it names.
    operations &= permissions.ON_AN_ACCOUNT
    return _Rule(
        accounts,
        operations,
        SendLimit(recipients, grant.max_sends_per_day),
        grant.expires_at,
        frozenset(grant.folders) if grant.folders is not None else None,
    )


def _expired(rule: _Rule, now: datetime) -> bool:
    return rule.expires_at is not None and rule.expires_at <= now


def _service_operations(names: Iterable[str]) -> frozenset[str]:
    """The operations of the service that ``names`` give."""
    operations, _ = permissions.expand_known(names)
    return operations & permissions.SERVICE


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
