"""The stores a tool opens on its own, outside a running service: a
backup, a restore, a move. They are those of the storage of
mailbox-common (``stores``), with the shape of the service, so the tools
name neither ``Database`` nor a place."""

from __future__ import annotations

import functools

from benethos_mailbox_common.storage import move, stores

from ...errors import STORAGE_ERRORS
from .sql import SHAPE

Claim = stores.Claim
# The database of the service in a file, in memory without a path.
file_store = functools.partial(stores.file_store, SHAPE)
# A database file from a backup brought to this version's schema.
migrate_file = functools.partial(stores.migrate_file, SHAPE)
# The lock a running service holds beside its file, for a tool.
file_claimed = functools.partial(
    stores.file_claimed, errors=STORAGE_ERRORS, noun="service"
)
# A schema on a server, held by a tool alone.
claimed = functools.partial(stores.claimed, SHAPE)

# The move of the records between the file and a schema on a server.
MoveError = move.MoveError
check_move = functools.partial(move.check_move, SHAPE)
move_records = functools.partial(move.move_records, SHAPE)
