"""The message id mapping, folder states and threads in SQL."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa

from ..index import IndexChanges, IndexEntry, ThreadChain
from .dialect import in_chunks, insert_or_skip
from .schema import folder_states, message_index, thread_links

if TYPE_CHECKING:
    from .database import Database

_m = message_index.c
_t = thread_links.c
_f = folder_states.c


class SqlMessageIndexRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, account_id: str, message_id: str) -> IndexEntry | None:
        with self._db.connected() as conn:
            row = (
                conn.execute(
                    sa.select(message_index).where(
                        _m.account_id == account_id, _m.id == message_id
                    )
                )
                .mappings()
                .first()
            )
        return None if row is None else _entry(row)

    def by_native(
        self, account_id: str, native_ids: Iterable[str]
    ) -> dict[str, IndexEntry]:
        rows = self._rows_in(account_id, _m.native_id, native_ids)
        return {row["native_id"]: _entry(row) for row in rows}

    def in_folders(
        self, account_id: str, folder_ids: Iterable[str]
    ) -> list[IndexEntry]:
        rows = self._rows_in(account_id, _m.folder_id, folder_ids)
        # In the order the entries came, across the chunks of the query.
        return [_entry(row) for row in sorted(rows, key=lambda row: row["seq"])]

    def with_header(self, account_id: str, headers: Iterable[str]) -> list[IndexEntry]:
        return [_entry(row) for row in self._rows_in(account_id, _m.header, headers)]

    def _rows_in(
        self, account_id: str, column: sa.ColumnElement[Any], values: Iterable[str]
    ) -> list[sa.RowMapping]:
        """The entries of the account whose ``column`` is one of
        ``values``, chunk by chunk."""
        rows: list[sa.RowMapping] = []
        for chunk in in_chunks(values):
            with self._db.connected() as conn:
                rows += conn.execute(
                    sa.select(message_index).where(
                        _m.account_id == account_id, column.in_(chunk)
                    )
                ).mappings()
        return rows

    def add(self, account_id: str, entries: Iterable[IndexEntry]) -> None:
        with self._db.connected() as conn:
            _insert(conn, account_id, entries)

    def apply(self, account_id: str, changes: IndexChanges) -> None:
        """Everything in one transaction."""
        with self._db.connected() as conn:
            _remove(conn, account_id, changes.removed)
            for entry in changes.updated:
                _update(conn, account_id, entry)
            _insert(conn, account_id, changes.added)
            conn.execute(sa.delete(folder_states).where(_f.account_id == account_id))
            states = [
                {"account_id": account_id, "folder_id": f, "state": s}
                for f, s in changes.states.items()
            ]
            if states:
                conn.execute(sa.insert(folder_states), states)

    def relocate(self, account_id: str, entry: IndexEntry) -> None:
        with self._db.connected() as conn:
            _update(conn, account_id, entry)

    def drop(self, account_id: str, message_id: str) -> None:
        with self._db.connected() as conn:
            _remove(conn, account_id, [message_id])

    def folder_states(self, account_id: str) -> dict[str, str]:
        with self._db.connected() as conn:
            rows = conn.execute(
                sa.select(_f.folder_id, _f.state).where(_f.account_id == account_id)
            )
            return {folder: state for folder, state in rows}

    def folders(self, account_id: str) -> set[str]:
        with self._db.connected() as conn:
            found = conn.execute(
                sa.select(_m.folder_id).distinct().where(_m.account_id == account_id)
            ).scalars()
            return set(found)

    def forget_account(self, account_id: str) -> None:
        with self._db.connected() as conn:
            for table in (message_index, folder_states, thread_links):
                conn.execute(sa.delete(table).where(table.c.account_id == account_id))
        # The index of an account is most of the file: give its pages back.
        self._db.shrink()

    # --- threads ----------------------------------------------------------------------

    def thread(
        self,
        account_id: str,
        chains: Iterable[ThreadChain],
        new_thread: Callable[[], str],
    ) -> dict[str, str]:
        chains = list(chains)
        merged: dict[str, str] = {}
        with self._db.connected() as conn:
            for chain in chains:
                merged.update(_join(conn, account_id, chain, new_thread))
        for chain in chains:
            merged.pop(chain.message_id, None)
        return merged

    def threads_of(self, account_id: str, message_ids: Iterable[str]) -> dict[str, str]:
        found: dict[str, str] = {}
        for chunk in in_chunks(message_ids):
            with self._db.connected() as conn:
                rows = conn.execute(
                    sa.select(_m.id, _m.thread_id).where(
                        _m.account_id == account_id,
                        _m.thread_id.is_not(None),
                        _m.id.in_(chunk),
                    )
                )
                found.update((message_id, thread) for message_id, thread in rows)
        return found

    def in_thread(self, account_id: str, thread_id: str) -> list[IndexEntry]:
        return self._entries(
            sa.select(message_index)
            .where(_m.account_id == account_id, _m.thread_id == thread_id)
            .order_by(_m.seq)
        )

    def unthreaded(self, account_id: str, limit: int) -> list[IndexEntry]:
        return self._entries(
            sa.select(message_index)
            .where(_m.account_id == account_id, _m.thread_id.is_(None))
            .order_by(_m.seq)
            .limit(limit)
        )

    def _entries(self, query: sa.Select[Any]) -> list[IndexEntry]:
        with self._db.connected() as conn:
            return [_entry(row) for row in conn.execute(query).mappings()]


def _join(
    conn: sa.Connection,
    account_id: str,
    chain: ThreadChain,
    new_thread: Callable[[], str],
) -> dict[str, str]:
    """One message into its thread, as ``thread`` describes. Answers the
    messages whose thread changed by a merge."""
    row = conn.execute(
        sa.select(_m.thread_id).where(
            _m.account_id == account_id, _m.id == chain.message_id
        )
    ).first()
    if row is None:
        return {}
    headers = list(dict.fromkeys(chain.headers))
    # The oldest thread first: the one whose first link came first.
    born = sa.func.min(_t.seq).label("born")
    found = (
        list(
            conn.execute(
                sa.select(_t.thread_id, born)
                .where(_t.account_id == account_id, _t.header.in_(headers))
                .group_by(_t.thread_id)
                .order_by(born)
            ).scalars()
        )
        if headers
        else []
    )
    own = row.thread_id
    if own is not None and own not in found:
        found.append(own)  # without links: never the oldest
    thread = found[0] if found else new_thread()
    merged: dict[str, str] = {}
    for younger in found[1:]:
        for message_id in conn.execute(
            sa.select(_m.id).where(_m.account_id == account_id, _m.thread_id == younger)
        ).scalars():
            merged[message_id] = thread
        for table in (message_index, thread_links):
            conn.execute(
                sa.update(table)
                .where(table.c.account_id == account_id, table.c.thread_id == younger)
                .values(thread_id=thread)
            )
    if headers:
        conn.execute(
            insert_or_skip(thread_links, conn.dialect),
            [
                {"account_id": account_id, "header": header, "thread_id": thread}
                for header in headers
            ],
        )
    conn.execute(
        sa.update(message_index)
        .where(_m.account_id == account_id, _m.id == chain.message_id)
        .values(thread_id=thread)
    )
    return merged


def _remove(conn: sa.Connection, account_id: str, message_ids: list[str]) -> None:
    """Entries go. A thread without a message left loses its links."""
    threads: set[str] = set()
    for chunk in in_chunks(message_ids):
        threads |= set(
            conn.execute(
                sa.select(_m.thread_id)
                .distinct()
                .where(
                    _m.account_id == account_id,
                    _m.thread_id.is_not(None),
                    _m.id.in_(chunk),
                )
            ).scalars()
        )
    if message_ids:
        conn.execute(
            sa.delete(message_index).where(
                _m.account_id == account_id, _m.id == sa.bindparam("gone")
            ),
            [{"gone": message_id} for message_id in message_ids],
        )
    _prune(conn, account_id, threads)


def _prune(conn: sa.Connection, account_id: str, threads: Iterable[str]) -> None:
    left = [{"thread": thread} for thread in threads]
    if not left:
        return
    thread: sa.BindParameter[str] = sa.bindparam("thread")
    conn.execute(
        sa.delete(thread_links).where(
            _t.account_id == account_id,
            _t.thread_id == thread,
            ~sa.exists().where(_m.account_id == account_id, _m.thread_id == thread),
        ),
        left,
    )


def _update(conn: sa.Connection, account_id: str, entry: IndexEntry) -> None:
    """The entry's new place. Another entry holding that place gives it up.
    An id the index does not know changes nothing. The thread stays."""
    known = conn.execute(
        sa.select(_m.id).where(_m.account_id == account_id, _m.id == entry.id)
    ).first()
    if known is None:
        return
    others = list(
        conn.execute(
            sa.select(_m.id).where(
                _m.account_id == account_id,
                _m.native_id == entry.native_id,
                _m.id != entry.id,
            )
        ).scalars()
    )
    if others:
        _remove(conn, account_id, others)
    conn.execute(
        sa.update(message_index)
        .where(_m.account_id == account_id, _m.id == entry.id)
        .values(
            native_id=entry.native_id, folder_id=entry.folder_id, header=entry.header
        )
    )


def _insert(
    conn: sa.Connection, account_id: str, entries: Iterable[IndexEntry]
) -> None:
    """Leaves out an entry whose id or place the index holds already."""
    rows = [
        {
            "id": e.id,
            "account_id": account_id,
            "native_id": e.native_id,
            "folder_id": e.folder_id,
            "header": e.header,
            "thread_id": e.thread_id,
        }
        for e in entries
    ]
    if rows:
        conn.execute(insert_or_skip(message_index, conn.dialect), rows)


def _entry(row: sa.RowMapping) -> IndexEntry:
    return IndexEntry(
        id=row["id"],
        native_id=row["native_id"],
        folder_id=row["folder_id"],
        header=row["header"],
        thread_id=row["thread_id"],
    )
