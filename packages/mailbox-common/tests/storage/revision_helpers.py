"""Folders of revisions for the tests of the storage, and the small
program they make: a first revision that makes ``meta`` and a table of
five items, and a second of a body the test gives."""

from __future__ import annotations

import textwrap
from pathlib import Path

import sqlalchemy as sa

from benethos_mailbox_common.storage.shape import Shape

# The first revision of each folder: meta, and a table of five items.
FIRST = """
    import sqlalchemy as sa
    from alembic import op
    from benethos_mailbox_common.storage.revision import Revision

    class R0026Items(Revision):
        baseline = 26
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
    from benethos_mailbox_common.storage.revision import Revision

    ITEMS = sa.table("items", sa.column("id"), sa.column("name"))

    class R0027Step(Revision):
        baseline = 26
        version = 27
{body}

    revision, down_revision, upgrade = R0027Step.alembic()
"""

# The tables of the program the first revision makes.
METADATA = sa.MetaData()
sa.Table(
    "meta",
    METADATA,
    sa.Column("key", sa.Text, primary_key=True),
    sa.Column("value", sa.Text),
)
sa.Table(
    "items",
    METADATA,
    sa.Column("id", sa.Text, primary_key=True),
    sa.Column("name", sa.Text),
    sa.Column("folded", sa.Text),
)


def second(body: str) -> str:
    """The second revision with ``body`` as its class body."""
    inner = textwrap.indent(textwrap.dedent(body).strip("\n"), " " * 8)
    return textwrap.dedent(SECOND.format(body=inner))


def steps_in(folder: Path, body: str) -> Path:
    """``folder`` with the first revision and a second of ``body``."""
    first_in(folder)
    (folder / "r0027_step.py").write_text(second(body), encoding="utf-8")
    return folder


def first_in(folder: Path, *, items: bool = True) -> Path:
    """``folder`` with the first revision alone, without its five items
    when not ``items``: a database it makes then holds no record."""
    folder.mkdir(exist_ok=True)
    first = textwrap.dedent(FIRST)
    if not items:
        first = first.replace("op.bulk_insert(items, ", "(")
    (folder / "r0026_items.py").write_text(first, encoding="utf-8")
    return folder


def program(folder: Path, newest: int = 26) -> Shape:
    """The program whose revisions lie in ``folder``, at ``newest``."""
    return Shape(
        program="benethos-mailbox-test",
        noun="test program",
        metadata=METADATA,
        versions=folder,
        newest=newest,
        baseline=26,
    )
