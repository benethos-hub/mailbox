"""The state file: its tables, the old steps of its file and its
revisions, one database per agent on the storage of mailbox-common. See
docs/mailbox-agents/concept/state.md."""

from __future__ import annotations

from .actions import ActionRow
from .messages import STATES, MessageRow, State
from .migrations import MIGRATIONS
from .revisions import SCHEMA_VERSION
from .store import Migrated, Store, earlier_file, path_for

__all__ = [
    "MIGRATIONS",
    "SCHEMA_VERSION",
    "STATES",
    "ActionRow",
    "MessageRow",
    "Migrated",
    "State",
    "Store",
    "earlier_file",
    "path_for",
]
