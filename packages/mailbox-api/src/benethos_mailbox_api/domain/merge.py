"""Lists across accounts: where each account stands, the merge order, the
cursor that carries it, and running one step on every account at once."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

from ..data import opaque
from ..data.models import AccountFailure, MessageSummary
from ..errors import BadRequestError, MailboxApiError

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


def encode_cursor(positions: dict[str, Position]) -> str:
    state = {a: [p.folder_id, p.cursor, p.offset, p.done] for a, p in positions.items()}
    return opaque.encode(_CURSOR_PREFIX, state)


def decode_cursor(value: str) -> dict[str, Position]:
    try:
        state = opaque.decode(_CURSOR_PREFIX, value)
        return {
            account_id: Position(folder_id, cursor, int(offset), bool(done))
            for account_id, (folder_id, cursor, offset, done) in state.items()
        }
    except (ValueError, TypeError, AttributeError):
        raise BadRequestError("invalid cursor") from None


async def per_account(
    account_ids: list[str],
    run: Callable[[str], Awaitable[T]],
    failures: list[AccountFailure],
) -> dict[str, T]:
    """``run`` for every account at once. An account that fails goes to
    ``failures`` instead of failing the rest."""
    outcomes = await asyncio.gather(
        *(run(a) for a in account_ids), return_exceptions=True
    )
    results: dict[str, T] = {}
    for account_id, outcome in zip(account_ids, outcomes, strict=True):
        if isinstance(outcome, MailboxApiError):
            failures.append(
                AccountFailure(
                    account_id=account_id, code=outcome.code, message=outcome.message
                )
            )
        elif isinstance(outcome, BaseException):
            raise outcome
        else:
            results[account_id] = outcome
    return results
