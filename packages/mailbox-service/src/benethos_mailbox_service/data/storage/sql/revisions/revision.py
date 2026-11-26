"""The base of every revision: one step of the schema, numbered after the
schema it makes.

A revision is a class of ``Revision`` in a module ``rNNNN_<subject>.py``
of ``versions/``. It names its schema in ``version`` and makes its step
in ``steps``: the tables through ``alembic.op``, the rows through
``conn``, ``rewrite`` for rows worked out in Python. ``check`` may hold
the result to what it must be, ``refuse`` stops the step with a message,
``note`` leaves a line for the start of the service. ``keeps_copy`` asks
for a copy of the database file before the step, ``in_transaction =
False`` runs it outside a transaction, as some steps on a server must.

After the step and its check the number goes into ``meta``, in the same
transaction, so ``meta.schema_version`` stays the one number of a schema.
The module hands Alembic what Alembic reads from it:
``revision, down_revision, upgrade = RNNNN<Subject>.alembic()``.
Only forward: a revision has no way back.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping, Sequence
from itertools import chain
from typing import Any, ClassVar

import sqlalchemy as sa
from alembic import op

from .....errors import StorageError
from ..dialect import TEXT, insert_or_update

# The schema the first revision makes, the last step of the old chain.
BASELINE = 26
# The rows ``rewrite`` reads at once.
REWRITE_CHUNK = 500
# Where a run collects what its revisions note, in the attributes of the
# configuration of Alembic.
NOTES = "notes"

# The table meta as a revision writes it, apart from the definitions,
# which may change after a revision is frozen.
_META = sa.Table(
    "meta",
    sa.MetaData(),
    sa.Column("key", TEXT, primary_key=True),
    sa.Column("value", TEXT),
)


def name_of(version: int) -> str:
    """The name of the revision that makes schema ``version``."""
    return f"{version:04d}"


class Revision(ABC):
    """One step of the schema, from the schema before ``version`` to it."""

    # The schema this step makes.
    version: ClassVar[int]
    # A copy of the database file before the step, beside it, kept.
    keeps_copy: ClassVar[bool] = False
    # False: the step runs outside a transaction, and what it did stays
    # when it fails. Its check and its number follow in one.
    in_transaction: ClassVar[bool] = True

    @abstractmethod
    def steps(self) -> None:
        """The step itself."""

    def check(self) -> None:
        """What must hold after the step, before its number is written.
        ``refuse`` when it does not. Nothing by default."""
        return None

    @property
    def conn(self) -> sa.Connection:
        """The connection the step runs on."""
        return op.get_bind()

    def note(self, text: str) -> None:
        """A line for the start of the service, which names what opening
        did to the database. No value of a row: the line is logged."""
        config = op.get_context().config
        if config is not None:
            config.attributes.setdefault(NOTES, []).append(
                f"schema {self.version}: {text}"
            )

    def refuse(self, text: str) -> None:
        """Stop the step: nothing of it stays, the schema stays where it
        was, and opening the database fails with ``text``. No value of a
        row: the text is logged."""
        raise StorageError(f"schema {self.version} cannot be reached: {text}")

    def rewrite(
        self,
        table: str,
        *,
        key: Sequence[str],
        read: Sequence[str],
        write: Sequence[str],
        change: Callable[[Mapping[str, Any]], Mapping[str, Any]],
    ) -> int:
        """Every row of ``table`` worked out anew in Python: ``change``
        gets the columns ``key`` and ``read`` of a row and answers the
        values of the columns ``write``. Read in chunks in the order of
        ``key``, so the table is never in memory at once. Answers how
        many rows."""
        columns = list(dict.fromkeys(chain(key, read, write)))
        rows = sa.table(table, *(sa.column(name) for name in columns))
        keys = [rows.c[name] for name in key]
        query = sa.select(*(rows.c[name] for name in dict.fromkeys(chain(key, read))))
        after: tuple[Any, ...] | None = None
        count = 0
        while True:
            chunk = query.order_by(*keys).limit(REWRITE_CHUNK)
            if after is not None:
                chunk = chunk.where(sa.tuple_(*keys) > sa.tuple_(*after))
            found = self.conn.execute(chunk).mappings().all()
            for row in found:
                values = change(dict(row))
                if set(values) != set(write):
                    raise StorageError(
                        f"schema {self.version}: a change of {table} gave"
                        f" {sorted(values)}, not {sorted(write)}"
                    )
                where = [rows.c[name] == row[name] for name in key]
                self.conn.execute(sa.update(rows).where(*where).values(**values))
            count += len(found)
            if len(found) < REWRITE_CHUNK:
                return count
            after = tuple(found[-1][name] for name in key)

    def upgrade(self) -> None:
        """The step, its check, then its number into ``meta``."""
        if self.in_transaction:
            self.steps()
        else:
            with op.get_context().autocommit_block():
                self.steps()
        self.check()
        bind = op.get_bind()
        bind.execute(
            insert_or_update(_META, ["key"], ["value"], bind.dialect).values(
                key="schema_version", value=str(self.version)
            )
        )

    @classmethod
    def alembic(cls) -> tuple[str, str | None, Callable[[], None]]:
        """``revision``, ``down_revision`` and ``upgrade`` for the module
        of the revision. The baseline comes after none."""
        before = None if cls.version == BASELINE else name_of(cls.version - 1)
        return name_of(cls.version), before, lambda: cls().upgrade()
