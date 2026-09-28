"""A sequence in slices, as ``itertools.batched`` of Python 3.12 does, which
the service cannot use while it runs on 3.11."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Any, TypeVar, cast

S = TypeVar("S", bound=Sequence[Any])


def batched(values: S, size: int) -> Iterator[S]:
    """``values`` in slices of ``size``, the last one shorter. A slice has
    the type of ``values``: a list gives lists, a string strings."""
    if size < 1:
        raise ValueError("a batch holds one value at least")
    for start in range(0, len(values), size):
        yield cast(S, values[start : start + size])
