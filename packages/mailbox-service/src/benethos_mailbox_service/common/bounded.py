"""Tables in memory that must not grow without bound, for the services.

What a caller can make the service remember, one entry per source, user
or domain, is capped: the entries that no longer count go first, then
the oldest.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable
from typing import Any, TypeVar

K = TypeVar("K", bound=Hashable)
V = TypeVar("V")


def trim(
    table: dict[K, V],
    most: int,
    *,
    gone: Callable[[V], bool],
    age: Callable[[V], Any],
    dropped: Callable[[K], object] = lambda key: None,
) -> None:
    """Keep at most ``most`` entries. Those ``gone`` picks go first, then
    those whose ``age`` is least. ``dropped`` hears of each key removed."""
    if len(table) <= most:
        return
    for key in [k for k, value in table.items() if gone(value)]:
        del table[key]
        dropped(key)
    while len(table) > most:
        key = min(table, key=lambda k: age(table[k]))
        del table[key]
        dropped(key)
