"""The catalogue of rights: every API operation and the group it belongs to.

A right is the name of an operation (its ``operationId``). Groups bundle
operations so grants stay readable. Every protected route must appear here,
the web layer refuses to start otherwise.
"""

from __future__ import annotations

from collections.abc import Iterable

ADMIN = "admin"

# Not a group that can be granted: operations every authenticated user may
# call, whatever its grants.
AUTHENTICATED = "authenticated"
AUTHENTICATED_OPERATIONS: frozenset[str] = frozenset({"get_me", "list_permissions"})

GROUPS: dict[str, tuple[str, ...]] = {
    "accounts.read": ("list_accounts", "get_account"),
    "mail.read": (
        "list_all_messages",
        "list_folders",
        "list_messages",
        "get_message",
        "get_message_raw",
        "get_attachment",
    ),
    "mail.write": ("update_message",),
    "accounts.manage": (
        "discover_account",
        "create_account",
        "delete_account",
        "verify_account",
    ),
    "users.manage": (
        "list_users",
        "create_user",
        "get_user",
        "update_user",
        "delete_user",
        "list_tokens",
        "create_token",
        "revoke_token",
        "list_roles",
        "create_role",
        "get_role",
        "replace_role",
        "delete_role",
    ),
}

# Operations that do not act on one account. A grant allows them regardless
# of the accounts it names.
ACCOUNT_FREE: frozenset[str] = frozenset(GROUPS["users.manage"])

# Operations that act on accounts which may not exist yet. They need a grant
# on every account ("*").
ALL_ACCOUNTS: frozenset[str] = frozenset({"discover_account", "create_account"})

GROUP_OF: dict[str, str] = {op: group for group, ops in GROUPS.items() for op in ops}


def permission_of(operation: str) -> str | None:
    """The group an operation belongs to, ``authenticated`` for operations
    open to every caller, or ``None`` if it is not in the catalogue."""
    if operation in AUTHENTICATED_OPERATIONS:
        return AUTHENTICATED
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
