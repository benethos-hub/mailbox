"""Errors surfaced to the MCP client.

``ToolError`` derives from the SDK's. That is what marks a failure as
anticipated and delivers its message to the model. Anything else raised
in a tool reaches the model only as "the tool failed", so the server
turns each error of the REST client into one (``for_the_model``).
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
    "reason",
]


class ToolError(_McpToolError):
    """An anticipated failure, its message shown to the model as is."""


def for_the_model(exc: MailboxError) -> ToolError:
    """The REST client's error, with its message, as one the model reads."""
    return ToolError(str(exc))


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
    return "the arguments were refused"
