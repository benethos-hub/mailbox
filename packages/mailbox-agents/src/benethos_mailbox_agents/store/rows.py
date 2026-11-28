"""What every part of the state file stands on: the database of the
storage of mailbox-common, the name of the file, the way a part reads and
writes in a transaction, and a time as it is stored. :class:`store.Store`
is made of the parts."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import sqlalchemy as sa

from benethos_mailbox_common.storage import clock, database

from ..errors import StateFileError

# What the parts of the store take from here.
__all__ = ["_Rows", "_named", "_text", "_time"]

# A time as the storage of mailbox-common writes and reads it, in UTC.
_text = clock.iso
_time = clock.parse_iso


@contextmanager
def _named(name: str) -> Iterator[None]:
    """An error of the state file named by its file. A text it cannot
    write as UTF-8 is named so, without the text."""
    try:
        yield
    except UnicodeEncodeError:
        raise StateFileError(
            f"the state file {name}: a text that is not valid UTF-8"
        ) from None
    except StateFileError as exc:
        raise type(exc)(f"the state file {name}: {exc.message}") from None


class _Rows:
    """The database a part of the store reads and writes through."""

    _db: database.Database
    _name: str

    @contextmanager
    def _conn(self) -> Iterator[sa.Connection]:
        """The connection, in one transaction, or in the one open."""
        with _named(self._name), self._db.connected() as conn:
            yield conn

    @property
    def version(self) -> int:
        """The schema the state file is at."""
        with _named(self._name):
            return self._db.schema_version()
