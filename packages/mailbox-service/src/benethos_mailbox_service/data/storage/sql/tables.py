"""What of the tables of the export is the service's own: the counter of
the change feed, set on after the rows of its table were written back,
so a feed whose newest rows were purged never hands a number out again.
The rest of the export is the storage of mailbox-common (``tables``)."""

from __future__ import annotations

import sqlalchemy as sa

from benethos_mailbox_common.storage import dialect

from .schema import changes, meta

# The key in ``meta`` of the last number the change feed handed out.
CHANGES_LAST = "changes_last"


def align_changes(conn: sa.Connection) -> None:
    """The counter of the change feed at least at the last number handed
    out, so a feed whose newest rows were purged never hands one out
    again."""
    last = conn.execute(
        sa.select(meta.c.value).where(meta.c.key == CHANGES_LAST)
    ).scalar()
    if last is not None:
        dialect.count_on_from(conn, changes, int(last))
