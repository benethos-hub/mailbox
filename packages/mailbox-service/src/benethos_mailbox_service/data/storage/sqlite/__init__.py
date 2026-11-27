"""The file of SQLite of the service: the old steps of its schema up to
26. The only package of the service that imports ``sqlite3``. The file
itself is the storage of mailbox-common (``sqlite_file``), whose names a
caller takes from here, with the service's word where one is said."""

from __future__ import annotations

import functools

from benethos_mailbox_common.storage import sqlite_file

from . import file
from .file import OLD_STEPS
from .migrations import SCHEMA_VERSION

# The integrity and the schema of a database file, on disk or in memory.
inspect_file = functools.partial(sqlite_file.inspect_file, noun="service")
inspect_bytes = functools.partial(sqlite_file.inspect_bytes, noun="service")
move_sidecars = sqlite_file.move_sidecars
remove_database_file = sqlite_file.remove_database_file
# The lock file a running service holds beside its database.
service_lock = sqlite_file.lock_file

__all__ = [
    "OLD_STEPS",
    "SCHEMA_VERSION",
    "file",
    "inspect_bytes",
    "inspect_file",
    "move_sidecars",
    "remove_database_file",
    "service_lock",
]
