"""The catalogue of rights: every API operation and the group it belongs to.

A right is the name of an operation (its ``operationId``). Groups bundle
operations so grants stay readable. Every protected route must appear here,
the web layer refuses to start otherwise.
"""

from __future__ import annotations

from collections.abc import Iterable

from ..errors import BadRequestError

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
    # batch_messages also needs the right of the single operation.
    "mail.write": (
        "update_message",
        "delete_message",
        "batch_messages",
        "create_folder",
        "update_folder",
    ),
    # Cannot be taken back. delete_message_permanent is DELETE with
    # permanent=true: a right of its own, not a route.
    "mail.delete": ("delete_message_permanent", "delete_folder"),
    # Reach drafts only, never other mail. A draft with a reference needs
    # get_message too.
    "drafts": ("list_drafts", "create_draft", "update_draft", "delete_draft"),
    # Cannot be taken back either.
    "send": ("send_message", "send_draft"),
    # Who sent what to whom, never content.
    "audit": ("list_sends",),
    "accounts.manage": (
        "discover_account",
        # Connecting needs create_account, signing in again update_account:
        # the domain checks those.
        "start_oauth",
        "create_account",
        "update_account",
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
ALL_ACCOUNTS: frozenset[str] = frozenset(
    {"discover_account", "create_account", "start_oauth"}
)

GROUP_OF: dict[str, str] = {op: group for group, ops in GROUPS.items() for op in ops}


def permission_of(operation: str) -> str | None:
    """The group an operation belongs to, ``authenticated`` for operations
    open to every caller, or ``None`` if it is not in the catalogue."""
    if operation in AUTHENTICATED_OPERATIONS:
        return AUTHENTICATED
    return GROUP_OF.get(operation)


def summarize(
    operations: Iterable[str], scope: Iterable[str]
) -> tuple[list[str], list[str]]:
    """``operations`` as whole groups and single operations, for display.
    A group counts as whole when every one of its operations in ``scope``
    is among them. The rest are single operations."""
    held = frozenset(operations)
    within = frozenset(scope)
    groups: list[str] = []
    covered: set[str] = set()
    for group, members in GROUPS.items():
        part = frozenset(members) & within
        if part and part <= held:
            groups.append(group)
            covered |= part
    return groups, sorted(held - covered)


def expand(names: Iterable[str]) -> frozenset[str]:
    """Group and operation names to the set of operations they allow. A
    name that is none of these is refused."""
    result: set[str] = set()
    for name in names:
        if name == ADMIN:
            result.update(GROUP_OF)
        elif name in GROUPS:
            result.update(GROUPS[name])
        elif name in GROUP_OF:
            result.add(name)
        else:
            raise BadRequestError(f"unknown right: {name}")
    return frozenset(result)


def expand_known(names: Iterable[str]) -> tuple[frozenset[str], list[str]]:
    """``expand`` for names read back from storage: the operations of the
    names still known, and the names that are not. A right renamed since
    the grant was written grants nothing, and must not lock everyone out."""
    unknown = [n for n in names if n != ADMIN and n not in GROUPS and n not in GROUP_OF]
    return expand(n for n in names if n not in unknown), unknown


def known_names() -> frozenset[str]:
    """Every name a grant may use: groups, operations and ``admin``."""
    return frozenset(GROUPS) | frozenset(GROUP_OF) | {ADMIN}
