"""Any route of the API, for what the endpoints do not cover: the
request as the caller spells it, its answer as JSON as it comes."""

from __future__ import annotations

from typing import Any

from ..calls import Call, as_is, given


def request(
    method: str,
    where: str,
    *,
    params: dict[str, Any] | None = None,
    json: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> Call[Any]:
    """Any request, answered with its JSON as it comes, None for no
    content. Parameters and fields that are None are left out."""
    return Call(
        method,
        where,
        as_is,
        params=given(params),
        json=given(json) if json is not None else None,
        headers=dict(headers or {}),
    )
