"""The catalogue of rights: every API operation and the group it belongs to.

A right is the name of an operation (its ``operationId``). Groups bundle
operations so grants stay readable. Every protected route must appear here,
the web layer refuses to start otherwise.
"""

from __future__ import annotations

from collections.abc import Iterable

ADMIN = "admin"

# Operations every authenticated user may call, whatever its grants.
AUTHENTICATED = "authenticated"

GROUPS: dict[str, tuple[str, ...]] = {
    "accounts.read": ("list_accounts", "get_account"),
    "mail.read": ("list_folders", "list_messages", "get_message"),
    "accounts.manage": ("create_account", "delete_account"),
}

# Operations that do not act on one account. A grant allows them regardless
# of the accounts it names.
ACCOUNT_FREE: frozenset[str] = frozenset()

# Operations that act on accounts which may not exist yet. They need a grant
# on every account ("*").
ALL_ACCOUNTS: frozenset[str] = frozenset({"create_account"})

GROUP_OF: dict[str, str] = {op: group for group, ops in GROUPS.items() for op in ops}


def permission_of(operation: str) -> str | None:
    """The group an operation belongs to, or ``None`` if it is not in the
    catalogue."""
    return GROUP_OF.get(operation)


def expand(names: Iterable[str]) -> frozenset[str]:
    """Group and operation names to the set of operations they allow."""
    result: set[str] = set()
    for name in names:
        if name == ADMIN:
            result.update(GROUP_OF)
        elif name in GROUPS:
            result.update(GROUPS[name])
        elif name in GROUP_OF:
            result.add(name)
        else:
            raise ValueError(f"unknown right: {name}")
    return frozenset(result)


def known_names() -> frozenset[str]:
    """Every name a grant may use: groups, operations and ``admin``."""
    return frozenset(GROUPS) | frozenset(GROUP_OF) | {ADMIN}
