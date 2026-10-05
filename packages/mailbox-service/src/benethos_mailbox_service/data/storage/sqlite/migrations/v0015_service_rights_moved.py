"""Schema 15: rights of the service leave the grants (PERMISSIONS.md 8.1).

A grant names rights on accounts from now on. What a stored grant named of
the service moves to the ``service`` list of its user or role, and nobody
loses a right:

- ``users.manage``, ``webhooks.manage`` and their operations move as they
  are. A grant gave them whatever accounts it named.
- ``admin`` on every account moves as ``admin``. An administrator could
  lift its own limits before, so a limit on such a grant goes with it.
- ``admin`` on named accounts gave every right on them and
  ``users.manage`` and ``webhooks.manage``. The grant keeps the groups on
  accounts, the two groups move.
- ``accounts.manage`` on every account could connect accounts. It gets
  ``accounts.connect``. ``discover_account``, ``create_account`` and
  ``start_oauth`` on every account move, on named accounts they gave
  nothing and are dropped.

A grant left with no right is dropped. The names are those of schema 14:
the catalogue may change, this step does not.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from .migration import Migration

_SERVICE_GROUPS = ("users.manage", "webhooks.manage")
_SERVICE_OPERATIONS = (
    "list_users",
    "create_user",
    "get_user",
    "update_user",
    "delete_user",
    "list_tokens",
    "create_token",
    "revoke_token",
    "set_password",
    "list_roles",
    "create_role",
    "get_role",
    "replace_role",
    "delete_role",
    "list_webhooks",
    "get_webhook",
    "create_webhook",
    "delete_webhook",
)
_CONNECT_OPERATIONS = ("discover_account", "create_account", "start_oauth")
# What admin gave on named accounts.
_ACCOUNT_GROUPS = (
    "accounts.read",
    "mail.read",
    "mail.write",
    "mail.delete",
    "drafts",
    "send",
    "audit",
    "accounts.manage",
)


def split(grants: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """The grants with rights on accounts alone, and the rights of the
    service they named."""
    kept: list[dict[str, Any]] = []
    service: list[str] = []
    for grant in grants:
        everywhere = "*" in grant.get("accounts", [])
        allow: list[str] = []
        for name in grant.get("allow", []):
            if name == "admin" and everywhere:
                service.append("admin")
            elif name == "admin":
                service += _SERVICE_GROUPS
                allow += _ACCOUNT_GROUPS
            elif name in _SERVICE_GROUPS or name in _SERVICE_OPERATIONS:
                service.append(name)
            elif name in _CONNECT_OPERATIONS:
                if everywhere:
                    service.append(name)
            else:
                allow.append(name)
                if name == "accounts.manage" and everywhere:
                    service.append("accounts.connect")
        if allow:
            kept.append({**grant, "allow": list(dict.fromkeys(allow))})
    return kept, list(dict.fromkeys(service))


class ServiceRightsMoved(Migration):
    version = 15
    statements = ()

    def before(self, db: sqlite3.Connection) -> list[str]:
        """Move the rights of the service, and say whose moved."""
        notes = []
        for table, what in (("users", "user"), ("roles", "role")):
            name = "name" if table == "users" else "id"
            rows = db.execute(f"SELECT id, {name}, grants FROM {table}").fetchall()
            for row in rows:
                grants, service = split(json.loads(row["grants"]))
                if not service and grants == json.loads(row["grants"]):
                    continue
                db.execute(
                    f"UPDATE {table} SET grants = ?, service = ? WHERE id = ?",
                    (json.dumps(grants), json.dumps(service), row["id"]),
                )
                if service:
                    notes.append(
                        f"{what} {row[name]}: {', '.join(service)} "
                        "moved from its grants to its rights of the service"
                    )
        return notes
