"""The catalogue of rights: every API operation and the group it belongs to.

A right is the name of an operation (its ``operationId``). Groups bundle
operations so grants stay readable. Every protected route must appear here,
the web layer refuses to start otherwise.

Two kinds of right (PERMISSIONS.md 8.1). Rights on accounts are named in
a grant, which says on which accounts. Rights of the service act on no
account and are named in the ``service`` list of a user or a role. One
group is in both lists: ``audit`` reads the sends of accounts in a
grant, and the audit of administration in ``service``.
"""

from __future__ import annotations

from collections.abc import Iterable

from ...errors import BadRequestError

ADMIN = "admin"

# Not a group that can be granted: operations every authenticated user may
# call, whatever its grants.
AUTHENTICATED = "authenticated"
AUTHENTICATED_OPERATIONS: frozenset[str] = frozenset({"get_me", "list_permissions"})

GROUPS: dict[str, tuple[str, ...]] = {
    # get_status: the accounts' sync and the worker, for the accounts the
    # caller may list.
    "accounts.read": ("list_accounts", "get_account", "get_status"),
    "mail.read": (
        "list_all_messages",
        "list_folders",
        "list_messages",
        "get_message",
        "get_message_raw",
        "get_attachment",
        "list_changes",
        "list_all_changes",
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
    # Who sent what to whom, never content. In service: who did what in
    # the service (docs/AUDIT.md).
    "audit": ("list_sends", "list_all_sends", "list_activity"),
    # Signing in again by OAuth is update_account: the domain checks it.
    "accounts.manage": ("update_account", "delete_account", "verify_account"),
    # Accounts that do not exist yet. Connecting by OAuth needs
    # create_account as well: the domain checks it.
    "accounts.connect": (
        "discover_account",
        "start_device_oauth",
        "poll_device_oauth",
        "create_account",
    ),
    # Who exists, never a change. users.manage holds every one of them.
    "users.read": ("list_users", "get_user", "list_tokens", "list_roles", "get_role"),
    "users.manage": (
        "list_users",
        "create_user",
        "get_user",
        "update_user",
        "delete_user",
        "list_tokens",
        "create_token",
        "revoke_token",
        "set_password",
        "remove_second_factor",
        "list_roles",
        "create_role",
        "get_role",
        "replace_role",
        "delete_role",
    ),
    # Webhooks hear of the accounts their creator may read, checked when
    # they are posted.
    "webhooks.manage": (
        "list_webhooks",
        "get_webhook",
        "create_webhook",
        "delete_webhook",
    ),
}

# The groups of the service: named in ``service``. Never in a grant,
# but for those in both lists.
SERVICE_GROUPS: tuple[str, ...] = (
    "accounts.connect",
    "users.read",
    "users.manage",
    "webhooks.manage",
    "audit",
)
# The groups in both lists: in a grant they give their operations on
# accounts, in ``service`` those of the service.
SHARED_GROUPS: tuple[str, ...] = ("audit",)

# Rights only ``admin`` gives, in no group and not to be granted by name.
# Showing the recovery key hands out the master key, which opens every
# stored secret. The service log names users, addresses and accounts.
ADMIN_ONLY: frozenset[str] = frozenset({"show_recovery_key", "read_service_log"})

# Each operation's group. One in two groups belongs to the smaller one,
# which comes first: list_users to users.read.
GROUP_OF: dict[str, str] = {}
for _group, _operations in GROUPS.items():
    for _operation in _operations:
        GROUP_OF.setdefault(_operation, _group)

# Operations on mail in folders: those a grant's folders narrow.
IN_FOLDERS: frozenset[str] = frozenset(
    GROUPS["mail.read"] + GROUPS["mail.write"] + GROUPS["mail.delete"]
)

# The operations of the service, and those on one existing account.
SERVICE: frozenset[str] = (
    frozenset(
        op
        for group in SERVICE_GROUPS
        if group not in SHARED_GROUPS
        for op in GROUPS[group]
    )
    | {"list_activity"}
    | ADMIN_ONLY
)
ON_AN_ACCOUNT: frozenset[str] = frozenset(GROUP_OF) - SERVICE


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
    whole = {
        group: part
        for group, members in GROUPS.items()
        if (part := frozenset(members) & within) and part <= held
    }
    # A group inside a larger one held whole is not named as well.
    groups = [
        group
        for group, part in whole.items()
        if not any(part < other for other in whole.values())
    ]
    covered = frozenset[str]().union(*whole.values())
    return groups, sorted(held - covered)


def expand(names: Iterable[str]) -> frozenset[str]:
    """Group and operation names to the set of operations they allow. A
    name that is none of these is refused."""
    result: set[str] = set()
    for name in names:
        if name == ADMIN:
            result.update(GROUP_OF)
            result.update(ADMIN_ONLY)
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
    known = known_names()
    unknown = [n for n in names if n not in known]
    return expand(n for n in names if n not in unknown), unknown


def known_names() -> frozenset[str]:
    """Every name a grant or ``service`` may use: groups, operations and
    ``admin``."""
    return frozenset(GROUPS) | frozenset(GROUP_OF) | {ADMIN}


def is_service(name: str) -> bool:
    """Whether a name is a right of the service alone: ``admin``, a group
    of the service that is in no grant, or one of its operations."""
    return (
        name == ADMIN
        or (name in SERVICE_GROUPS and name not in SHARED_GROUPS)
        or name in SERVICE
    )


def of_scope(name: str, scope: frozenset[str]) -> tuple[str, ...]:
    """The operations a group or operation name gives within ``scope``:
    ``SERVICE`` for the list ``service``, ``ON_AN_ACCOUNT`` for a grant."""
    if name == ADMIN:
        return tuple(sorted(scope))
    return tuple(op for op in GROUPS.get(name, (name,)) if op in scope)


def check_grant(names: Iterable[str]) -> None:
    """Refuse a name a grant may not use: unknown, or a right of the
    service, which belongs in ``service``."""
    for name in names:
        if name not in known_names():
            raise BadRequestError(f"unknown right: {name}")
        if is_service(name):
            raise BadRequestError(
                f"{name} is a right of the service: name it in service, not in a grant"
            )


def check_service(names: Iterable[str]) -> None:
    """Refuse a name ``service`` may not hold: unknown, or a right on
    accounts, which belongs in a grant."""
    for name in names:
        if name not in known_names():
            raise BadRequestError(f"unknown right: {name}")
        if not is_service(name) and name not in SHARED_GROUPS:
            raise BadRequestError(
                f"{name} is a right on accounts: name it in a grant, not in service"
            )
