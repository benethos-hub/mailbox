"""The states a reader finds on a PostgreSQL server, signed in with its
own role, such as the read role of the cockpit: each database it may
connect to, and in it each schema where it may read the table
``profile``. That is an instance whose owner gave it the read, and
nothing else is found. See docs/mailbox-agents/concept/cockpit.md.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from benethos_mailbox_common.storage import server_catalogue, server_place

from ..errors import MailboxAgentError
from .shape import SHAPE

# The server a state lies on, for those who hold one without the storage.
Server = server_place.Server

__all__ = ["Found", "Server", "states_on"]

# The table every state holds, which its owner gives to read with it.
_MARK = "profile"


@dataclass(frozen=True, slots=True)
class Found:
    """A state a reader found, or what it could not read: ``name`` the
    database, with the schema after it where the database holds several,
    or the server where it was not reached. ``server`` reaches the state,
    ``error`` says why there is none."""

    name: str
    server: server_place.Server | None = None
    error: MailboxAgentError | None = None


def states_on(server: server_place.Server) -> list[Found]:
    """Every state the role of ``server`` may read on it, found from the
    database ``server`` names, by name."""
    try:
        databases = server_catalogue.readable_databases(server, SHAPE)
    except MailboxAgentError as exc:
        return [Found(f"{server.host}-{server.port}", error=exc)]
    found: list[Found] = []
    for database in databases:
        at = replace(server, database=database)
        try:
            schemas = server_catalogue.schemas_holding(at, _MARK, SHAPE)
        except MailboxAgentError as exc:
            found.append(Found(database, error=exc))
            continue
        for schema in schemas:
            name = database if len(schemas) == 1 else f"{database}-{schema}"
            found.append(Found(name, server=replace(at, schema=schema)))
    return found
