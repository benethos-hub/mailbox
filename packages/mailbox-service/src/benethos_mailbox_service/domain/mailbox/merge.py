"""Lists across accounts: where each account stands, the merge order, the
cursor that carries it, and running one step on every account at once."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypeVar

import anyio

from ...data.models import AccountFailure, MessageSummary, received_or_written
from ...errors import BadRequestError, MailboxServiceError
from .. import paging

T = TypeVar("T")

_CURSOR_PREFIX = "x_"


@dataclass
class Position:
    """Where one account stands in a list across accounts."""

    folder_id: str | None
    cursor: str | None  # the account's own cursor of the page to read next
    offset: int  # items of that page already delivered
    done: bool = False


@dataclass
class Chunk:
    cursor: str | None
    offset: int
    items: list[MessageSummary]
    next_cursor: str | None


def newest_first(item: MessageSummary) -> tuple[bool, float]:
    when = received_or_written(item)
    return (when is None, -when.timestamp() if when else 0.0)


def newest_of(
    windows: dict[str, list[Chunk]], limit: int
) -> list[tuple[MessageSummary, str]]:
    """The newest ``limit`` items of the windows, with their account, newest
    first. Each account gives a start of its own order, since its position
    counts what it gave: of the accounts' next items, the newest is taken
    first. A provider whose order is not by date (IMAP's by arrival) is
    then never skipped or given twice, though a page may hold a message
    older than one of the next page."""
    queues = [
        (account_id, [item for chunk in window for item in chunk.items])
        for account_id, window in windows.items()
    ]
    heads = [0] * len(queues)
    taken: list[tuple[MessageSummary, str]] = []
    while len(taken) < limit:
        waiting = [
            (newest_first(items[heads[n]]), n)
            for n, (_, items) in enumerate(queues)
            if heads[n] < len(items)
        ]
        if not waiting:
            break
        _, n = min(waiting)
        account_id, items = queues[n]
        taken.append((items[heads[n]], account_id))
        heads[n] += 1
    return sorted(taken, key=lambda pair: newest_first(pair[0]))


def advance(position: Position, window: list[Chunk], consumed: int) -> Position:
    """The position after ``consumed`` items of ``window`` were handed out."""
    for chunk in window:
        if consumed < len(chunk.items):
            return Position(position.folder_id, chunk.cursor, chunk.offset + consumed)
        consumed -= len(chunk.items)
    last = window[-1].next_cursor
    if last is None:
        return Position(position.folder_id, None, 0, done=True)
    return Position(position.folder_id, last, 0)


def encode_cursor(positions: dict[str, Position], query: str) -> str:
    state = {a: [p.folder_id, p.cursor, p.offset, p.done] for a, p in positions.items()}
    return paging.encode_cursor(_CURSOR_PREFIX, {"q": query, "at": state})


def decode_cursor(value: str, query: str) -> dict[str, Position]:
    """Where each account stands. A cursor of another search, folder or
    filter is refused: its positions mean nothing for this one."""

    def positions(state: Any) -> dict[str, Position]:
        if state["q"] != query:
            raise BadRequestError(
                "the cursor belongs to another search: start without it"
            )
        return {
            account_id: Position(folder_id, cursor, int(offset), bool(done))
            for account_id, (folder_id, cursor, offset, done) in state["at"].items()
        }

    return paging.decode_cursor(_CURSOR_PREFIX, value, positions)


async def per_account(
    account_ids: list[str],
    run: Callable[[str], Awaitable[T]],
    failures: list[AccountFailure],
) -> dict[str, T]:
    """``run`` for every account at once. An account that fails goes to
    ``failures`` instead of failing the rest."""
    results: dict[str, T] = {}

    async def one(account_id: str) -> None:
        try:
            results[account_id] = await run(account_id)
        except MailboxServiceError as exc:
            failures.append(
                AccountFailure(
                    account_id=account_id, code=exc.code, message=exc.message
                )
            )

    async with anyio.create_task_group() as group:
        for account_id in account_ids:
            group.start_soon(one, account_id)
    return results
