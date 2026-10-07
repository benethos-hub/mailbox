"""What a request asked for, as a short text that is the same for the same
request: a cursor carries the fingerprint of its search, a stored result
the fingerprint of the request its Idempotency-Key was sent with."""

from __future__ import annotations

from pydantic import BaseModel

from ...common.canonical import canonical
from ...common.secret import digest


def fingerprint(*values: BaseModel | str | None) -> str:
    """The SHA-256 of the values as JSON, keys sorted, a model as the JSON
    the API reads."""
    text = canonical(
        [v.model_dump(mode="json") if isinstance(v, BaseModel) else v for v in values]
    )
    return digest(text)
