"""The method responses of a request read, and JMAP's errors as this
project's."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from pydantic import BaseModel

from ....errors import (
    BadRequestError,
    ChangesExpiredError,
    ConflictError,
    MailboxServiceError,
    NotFoundError,
    NotSupportedError,
    ProviderAuthError,
    ProviderError,
    ProviderUnavailableError,
)
from .. import wire
from .shapes import Invocation, SetError

S = TypeVar("S", bound=BaseModel)


def result(responses: list[Invocation], tag: str) -> dict[str, Any]:
    """The arguments of the response to the call ``tag``. A method error
    raises as this project's error."""
    for name, args, answered in responses:
        if answered == tag:
            if name == "error":
                raise method_error(args)
            return args
    raise ProviderError("the JMAP server left a call unanswered")


def read(responses: list[Invocation], tag: str, shape: type[S]) -> S:
    """The response to the call ``tag``, read as ``shape``."""
    return wire.parse_value(
        shape,
        result(responses, tag),
        "the JMAP server answered a call in a shape of its own",
    )


def error_type(responses: list[Invocation], tag: str) -> str | None:
    """The type of the method error the call ``tag`` met, None without one."""
    for name, args, answered in responses:
        if answered == tag and name == "error":
            return _error(args).type
    return None


def method_error(args: Mapping[str, Any]) -> MailboxServiceError:
    """A method error (RFC 8620 3.6.2) as this project's error."""
    error = _error(args)
    kind = error.type
    text = f"jmap: {error.description or kind} ({kind})"
    if kind == "cannotCalculateChanges":
        return ChangesExpiredError(text)
    if kind in ("serverUnavailable", "rateLimit"):
        return ProviderUnavailableError(text)
    if kind in ("unknownMethod", "unsupportedFilter", "unsupportedSort"):
        return NotSupportedError(text)
    if kind in ("invalidArguments", "requestTooLarge", "anchorNotFound"):
        return BadRequestError(text)
    if kind == "forbidden":
        return ProviderAuthError(text)
    return ProviderError(text)


def set_error(error: SetError, what: str) -> MailboxServiceError:
    """A SetError (RFC 8620 5.3) for one object as this project's error.
    ``what``: what the object is, e.g. "message"."""
    kind = error.type
    text = f"jmap: {error.description or kind} ({kind})"
    if kind == "notFound":
        return NotFoundError(f"{what} not found")
    if kind in (
        "alreadyExists",
        "mailboxHasChild",
        "mailboxHasEmail",
        "overQuota",
        "stateMismatch",
        "willDestroy",
    ):
        return ConflictError(text)
    if kind in ("invalidProperties", "invalidPatch", "tooLarge", "singleton"):
        return BadRequestError(text)
    if kind in ("forbidden", "forbiddenFrom", "forbiddenToSend", "forbiddenMailFrom"):
        return ConflictError(text)
    return ProviderError(text)


def _error(args: Mapping[str, Any]) -> SetError:
    return wire.read_value(SetError, args) or SetError()
