"""Folders of revisions for the tests of the revisions: a first that
makes ``meta`` and a table of five items, and a second of a body the
test gives."""

from __future__ import annotations

import textwrap
from pathlib import Path

# The first revision of each folder: meta, and a table of five items.
FIRST = """
    import sqlalchemy as sa
    from alembic import op
    from benethos_mailbox_service.data.storage.sql.revisions import Revision

    class R0026Items(Revision):
        version = 26

        def steps(self):
            op.create_table("meta", sa.Column("key", sa.Text, primary_key=True),
                            sa.Column("value", sa.Text))
            items = op.create_table("items",
                                    sa.Column("id", sa.Text, primary_key=True),
                                    sa.Column("name", sa.Text),
                                    sa.Column("folded", sa.Text))
            op.bulk_insert(items, [{"id": f"i{n}", "name": f"Name {n}"}
                                   for n in range(5)])

    revision, down_revision, upgrade = R0026Items.alembic()
"""

# The second: its class body after the line ``version = 27``.
SECOND = """
    import sqlalchemy as sa
    from alembic import op
    from benethos_mailbox_service.data.storage.sql.revisions import Revision

    ITEMS = sa.table("items", sa.column("id"), sa.column("name"))

    class R0027Step(Revision):
        version = 27
{body}

    revision, down_revision, upgrade = R0027Step.alembic()
"""


def second(body: str) -> str:
    """The second revision with ``body`` as its class body."""
    inner = textwrap.indent(textwrap.dedent(body).strip("\n"), " " * 8)
    return textwrap.dedent(SECOND.format(body=inner))


def steps_in(folder: Path, body: str) -> Path:
    """``folder`` with the first revision and a second of ``body``."""
    folder.mkdir(exist_ok=True)
    (folder / "r0026_items.py").write_text(textwrap.dedent(FIRST), encoding="utf-8")
    (folder / "r0027_step.py").write_text(second(body), encoding="utf-8")
    return folder
