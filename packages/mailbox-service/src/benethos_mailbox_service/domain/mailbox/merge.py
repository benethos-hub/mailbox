"""Lists across accounts: where each account stands, the merge order, the
cursor that carries it, and running one step on every account at once."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

import anyio
from pydantic import BaseModel

from ...common import opaque
from ...data.models import AccountFailure, MessageSummary
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
    return (item.date is None, -item.date.timestamp() if item.date else 0.0)


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


def fingerprint(*query: BaseModel | str | None) -> str:
    """What a list was asked for, short. A cursor carries it, so that it
    continues the list it came from and no other."""
    canonical = json.dumps(
        [q.model_dump(mode="json") if isinstance(q, BaseModel) else q for q in query],
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def encode_cursor(positions: dict[str, Position], query: str) -> str:
    state = {a: [p.folder_id, p.cursor, p.offset, p.done] for a, p in positions.items()}
    return opaque.encode(_CURSOR_PREFIX, {"q": query, "at": state})


def decode_cursor(value: str, query: str) -> dict[str, Position]:
    """Where each account stands. A cursor of another search, folder or
    filter is refused: its positions mean nothing for this one."""
    state = paging.decode_cursor(_CURSOR_PREFIX, value)
    try:
        if state["q"] != query:
            raise BadRequestError(
                "the cursor belongs to another search: start without it"
            )
        return {
            account_id: Position(folder_id, cursor, int(offset), bool(done))
            for account_id, (folder_id, cursor, offset, done) in state["at"].items()
        }
    except (ValueError, TypeError, AttributeError, KeyError):
        raise BadRequestError("invalid cursor") from None


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
