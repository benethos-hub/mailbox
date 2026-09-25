"""A user's effective rights as the user page shows them.

The domain works out the rights: the user's grants and those of its roles
together. This module only groups the operations for reading. A group
whose operations are all held shows as the group, the rest as single
operations.
"""

from __future__ import annotations

from dataclasses import dataclass

from ...domain import permissions
from ...domain.access import SendLimit
from ...domain.users import EffectiveRights

# Operations bound to one existing account, and those that are not.
ON_AN_ACCOUNT = frozenset(permissions.GROUP_OF) - (
    permissions.ACCOUNT_FREE | permissions.ALL_ACCOUNTS
)
NOT_ON_AN_ACCOUNT = permissions.ACCOUNT_FREE | permissions.ALL_ACCOUNTS


@dataclass(frozen=True)
class AccountRow:
    email: str
    groups: list[str]
    operations: list[str]
    sending: list[SendLimit]
    warnings: list[str]


@dataclass(frozen=True)
class EffectiveView:
    accounts: list[AccountRow]
    groups: list[str]
    operations: list[str]


def view_of(rights: EffectiveRights) -> EffectiveView:
    rows = []
    for account in rights.accounts:
        groups, operations = permissions.summarize(account.operations, ON_AN_ACCOUNT)
        rows.append(
            AccountRow(
                email=account.email,
                groups=groups,
                operations=operations,
                sending=account.sending,
                warnings=account.warnings,
            )
        )
    groups, operations = permissions.summarize(rights.operations, NOT_ON_AN_ACCOUNT)
    return EffectiveView(accounts=rows, groups=groups, operations=operations)
