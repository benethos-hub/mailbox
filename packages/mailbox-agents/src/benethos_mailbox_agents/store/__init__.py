"""The state file: its tables, the old steps of its file and its
revisions, one database per agent on the storage of mailbox-common. See
docs/mailbox-agents/concept/state.md."""

from __future__ import annotations

from .actions import ActionRow
from .catalogue import LOGIN, READER, Found, Server, states_on
from .messages import STATES, MessageRow, State
from .migrations import MIGRATIONS
from .revisions import SCHEMA_VERSION
from .shape import SHAPE
from .store import Migrated, Store, earlier_file, path_for

__all__ = [
    "LOGIN",
    "MIGRATIONS",
    "READER",
    "SCHEMA_VERSION",
    "SHAPE",
    "STATES",
    "ActionRow",
    "Found",
    "MessageRow",
    "Migrated",
    "Server",
    "State",
    "Store",
    "earlier_file",
    "path_for",
    "states_on",
]
