"""The request a call makes, described without sending it: its method,
its path below ``/v1``, its parameters and body, how long to wait, and
how its answer becomes what the caller gets. ``client`` and ``sync``
send a ``Call``, each in its own way."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar
from urllib.parse import quote

import httpx

# Seconds to wait: for the service to take the connection, for an answer,
# and for an attachment, which may be large.
CONNECT_TIMEOUT = 5.0
TIMEOUT = 30.0
ATTACHMENT_TIMEOUT = 120.0

T = TypeVar("T")


@dataclass(frozen=True)
class Call(Generic[T]):
    """One request to the API, and how its answer becomes what the caller
    gets. ``read`` takes the JSON of the answer, None for no content."""

    method: str
    path: str
    read: Callable[[Any], T]
    params: dict[str, Any] = field(default_factory=dict)
    json: dict[str, Any] | None = None
    headers: dict[str, str] = field(default_factory=dict)
    timeout: float = TIMEOUT

    @property
    def timeouts(self) -> httpx.Timeout:
        return timeouts(self.timeout)


def timeouts(seconds: float = TIMEOUT) -> httpx.Timeout:
    """How long to wait for the connection, and then for the answer."""
    return httpx.Timeout(seconds, connect=CONNECT_TIMEOUT)


def given(values: Mapping[str, Any] | None) -> dict[str, Any]:
    """Without the entries that are None: those stay out of a request."""
    return {k: v for k, v in (values or {}).items() if v is not None}


def path(*parts: str) -> str:
    """A path below ``/v1``, each part quoted: an id may come from anyone."""
    return "/v1/" + "/".join(quote(part, safe="") for part in parts)


def as_is(found: Any) -> Any:
    """The reading of a call whose answer is passed on as it comes."""
    return found


def nothing(found: Any) -> None:
    """The reading of a call whose answer has no content."""
    return None
