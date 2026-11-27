"""The table ``meta``, where the storage of mailbox-common keeps the
schema of the file, as it does for every database it opens.

Up to schema 4 the file kept its schema in ``user_version`` alone, and
its steps ran on ``sqlite3``. From schema 5 on the revisions of the
storage run on it, on a file as on a server. This step is the last of
the old ones: it makes ``meta`` with the schema the file is now at, so
the revisions take the file up from there.
"""

from __future__ import annotations

from ..migration import Migration

__all__ = ["V0005Meta"]


class V0005Meta(Migration):
    version = 5
    statements = (
        """
            CREATE TABLE meta (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """,
        """
            INSERT INTO meta (key, value) VALUES ('schema_version', '5')
        """,
    )
