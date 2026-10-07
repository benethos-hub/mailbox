"""What a JMAP server sends, as shapes: the session resource, a response
and its method calls, the event stream, and the arguments of the
standard methods (RFC 8620 5). The mail objects are the adapter's."""

from __future__ import annotations

from typing import Annotated, Any, Generic, TypeVar

from pydantic import Field, NonNegativeInt, PositiveInt

from .. import wire

T = TypeVar("T")

OptionalText = Annotated[str | None, wire.OrNone]

# One call: the method, its arguments, and the tag that pairs it with its
# response.
Invocation = tuple[str, dict[str, Any], str]
# The state of each type of an account, as a StateChange names it.
States = dict[str, OptionalText]


# --- the session and a request ----------------------------------------------------


class Limits(wire.CamelShape):
    """What a capability says of the server's limits. Only the core
    capability's are read."""

    max_concurrent_requests: Annotated[PositiveInt | None, wire.OrNone] = None
    max_objects_in_get: Annotated[PositiveInt | None, wire.OrNone] = None


class AccountShape(wire.CamelShape):
    account_capabilities: dict[str, object] = {}


class SessionResource(wire.CamelShape):
    """The session resource (RFC 8620 2)."""

    capabilities: dict[str, Annotated[Limits | None, wire.OrNone]] = {}
    primary_accounts: dict[str, str] = {}
    accounts: dict[str, Annotated[AccountShape | None, wire.OrNone]] = {}
    api_url: str | None = None
    download_url: str | None = None
    upload_url: str | None = None
    event_source_url: str | None = None
    state: OptionalText = None


class Capabilities(wire.Shape):
    """No more of a session than its capabilities."""

    capabilities: dict[str, object]


class Reply(wire.CamelShape):
    """A response to a request (RFC 8620 3.4). A method response of
    another shape is left out."""

    method_responses: list[Annotated[Invocation | None, wire.OrNone]]
    session_state: OptionalText = None


class Uploaded(wire.CamelShape):
    blob_id: str


class StateChange(wire.Shape):
    """A StateChange (RFC 8620 7.1): the states of each account."""

    changed: dict[str, Annotated[States | None, wire.OrNone]]


class Problem(wire.Shape):
    """A problem details object (RFC 7807), as a refused request carries."""

    detail: OptionalText = None
    type: OptionalText = None


# --- the standard methods ---------------------------------------------------------


class SetError(wire.CamelShape):
    """Why an object was not created, updated or destroyed (RFC 8620
    5.3), or why a method failed (3.6.2)."""

    type: str = "serverFail"
    description: OptionalText = None


class Created(wire.CamelShape):
    id: str


class SetResult(wire.CamelShape):
    """The answer of a ``/set`` (RFC 8620 5.3) or ``/import`` (RFC 8621
    4.8)."""

    created: dict[str, Created] = {}
    not_created: dict[str, SetError] = {}
    not_updated: dict[str, SetError] = {}
    not_destroyed: dict[str, SetError] = {}


class Got(wire.CamelShape, Generic[T]):
    """The answer of a ``/get`` (RFC 8620 5.1)."""

    state: OptionalText = None
    items: list[T] = Field(default=[], alias="list")


class Queried(wire.CamelShape):
    """The answer of a ``/query`` (RFC 8620 5.5). ``limit`` only when the
    server cut the page shorter than asked."""

    ids: list[str] = []
    position: Annotated[NonNegativeInt | None, wire.OrNone] = None
    limit: Annotated[PositiveInt | None, wire.OrNone] = None


class Changed(wire.CamelShape):
    """The answer of a ``/changes`` (RFC 8620 5.2)."""

    new_state: OptionalText = None
    has_more_changes: bool = False
    created: list[str] = []
    updated: list[str] = []
    destroyed: list[str] = []


class Anything(wire.Shape):
    """An answer whose content does not matter, only that there is one."""
