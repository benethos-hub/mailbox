"""Errors surfaced to the MCP client.

Every class derives from the SDK's ``ToolError``. That is what marks a
failure as anticipated and delivers its message to the model. Anything else
raised in a tool reaches the model only as "the tool failed".
"""

from __future__ import annotations

from mcp.server.mcpserver.exceptions import ToolError as _McpToolError


class ToolError(_McpToolError):
    """An anticipated failure, its message shown to the model as is."""


class ServiceUnavailableError(ToolError):
    """The Mailbox API service is not running or not reachable."""


class ApiError(ToolError):
    """The REST API answered with an error envelope."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(f"{message} ({code}, HTTP {status})")
        self.status = status
        self.code = code
