"""The change feed: what changed in one account or in every account the
caller may read, since a state."""

from __future__ import annotations

from typing import Any

from ..calls import Call, given, path
from ..models import Change, Changes
from .readings import time


def list_all_changes(
    *,
    accounts: list[str] | None = None,
    since: str | None = None,
    limit: int | None = None,
) -> Call[Changes]:
    """The changes of every account the caller may read, or of those in
    ``accounts``, after the point ``since``. Without it, only the state
    to start from."""
    return Call(
        "GET",
        path("changes"),
        _changes,
        params=given({"accounts": accounts, "since": since, "limit": limit}),
    )


def list_changes(
    account_id: str, *, since: str | None = None, limit: int | None = None
) -> Call[Changes]:
    """The changes of one account after the point ``since``. Without it,
    only the state to start from. ``list_all_changes`` follows every
    account."""
    return Call(
        "GET",
        path("accounts", account_id, "changes"),
        _changes,
        params=given({"since": since, "limit": limit}),
    )


def _changes(found: dict[str, Any]) -> Changes:
    return Changes(
        changes=[
            Change(
                type=str(change["type"]),
                id=str(change["id"]),
                account_id=str(change["account_id"]),
                at=time(change["at"]),
            )
            for change in found.get("changes", [])
        ],
        state=str(found["state"]),
        more=bool(found.get("more")),
    )
