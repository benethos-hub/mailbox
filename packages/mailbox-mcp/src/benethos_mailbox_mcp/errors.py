"""Errors surfaced to the MCP client.

``ToolError`` derives from the SDK's. That is what marks a failure as
anticipated and delivers its message to the model. Anything else raised
in a tool reaches the model only as "the tool failed", so the server
turns each error of the REST client into one (``for_the_model``). What
an error tells of the token's rights is asked here too.
"""

from __future__ import annotations

from mcp.server.mcpserver.exceptions import ToolError as _McpToolError

from benethos_mailbox_client import (
    ApiError,
    ConfigurationError,
    MailboxError,
    ServiceTimeoutError,
    ServiceUnavailableError,
)

__all__ = [
    "ApiError",
    "ConfigurationError",
    "MailboxError",
    "ServiceTimeoutError",
    "ServiceUnavailableError",
    "ToolError",
    "for_the_model",
    "forbidden",
    "missing_right",
    "reason",
    "refused_token",
]

# What the service answers for a token it does not take, and for a call
# the caller may not make, the one for want of a right by its code.
_REFUSED = 401
_FORBIDDEN = 403
_MISSING_RIGHT = "forbidden"


class ToolError(_McpToolError):
    """An anticipated failure, its message shown to the model as is.
    ``kind`` says for the log what went wrong, without the message."""

    def __init__(self, message: str, kind: str = "the arguments were refused") -> None:
        super().__init__(message)
        self.kind = kind


def for_the_model(exc: MailboxError) -> ToolError:
    """The REST client's error, with its message, as one the model reads."""
    return ToolError(str(exc))


def refused_token(exc: MailboxError) -> bool:
    """Whether the service refused the token itself (HTTP 401)."""
    return isinstance(exc, ApiError) and exc.status == _REFUSED


def forbidden(exc: MailboxError) -> bool:
    """Whether the service refused the call to the caller, for whatever
    reason (HTTP 403)."""
    return isinstance(exc, ApiError) and exc.status == _FORBIDDEN


def missing_right(exc: MailboxError) -> bool:
    """Whether the service refused the call for want of a right, which
    may have been taken away."""
    return (
        isinstance(exc, ApiError)
        and exc.status == _FORBIDDEN
        and exc.code == _MISSING_RIGHT
    )


def reason(exc: Exception) -> str:
    """Why a tool failed, for the log: never the message, which may repeat
    an address or a search term the model sent."""
    if isinstance(exc, ApiError):
        return f"{exc.code} (HTTP {exc.status})"
    if isinstance(exc, ServiceUnavailableError):
        return "mailbox-service is not reachable"
    if isinstance(exc, ServiceTimeoutError):
        return "mailbox-service did not answer in time"
    if isinstance(exc, ConfigurationError):
        return "the REST client is not configured"
    if isinstance(exc, ToolError):
        return exc.kind
    return "the arguments were refused"
