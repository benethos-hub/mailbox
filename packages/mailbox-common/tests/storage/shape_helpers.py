"""A small database of a program for the tests of the storage: ``meta``
alone, the errors of the group's own."""

from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa

from benethos_mailbox_common.storage.shape import Shape

METADATA = sa.MetaData()
sa.Table(
    "meta",
    METADATA,
    sa.Column("key", sa.Text, primary_key=True),
    sa.Column("value", sa.Text, nullable=False),
)
SHAPE = Shape(
    program="benethos-mailbox-test",
    noun="test",
    metadata=METADATA,
    versions=Path("versions"),
    newest=1,
    baseline=1,
)
