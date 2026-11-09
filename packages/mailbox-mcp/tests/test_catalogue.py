"""The catalogue: every tool listed, none run, without a service or a
token, for a directory that reads the tool list in a sandbox."""

from __future__ import annotations

import json
import re
from collections.abc import Callable

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from benethos_mailbox_mcp import cli, server
from benethos_mailbox_mcp import tools as catalogue

EVERY_OPERATION = {need for tool in catalogue.TOOLS for need in tool.needs}


async def test_it_lists_every_tool_as_a_server_with_every_right() -> None:
    """The same names, descriptions, schemas and hints as a server whose
    token may do everything."""
    listed = await server.build_catalogue().list_tools()
    full = await server.build_server(EVERY_OPERATION).list_tools()
    assert {tool.name for tool in listed} == {
        tool.fn.__name__ for tool in catalogue.TOOLS
    }
    assert [tool.model_dump() for tool in listed] == [
        tool.model_dump() for tool in full
    ]


async def test_a_tool_refuses_its_call_and_reaches_no_service(api: Callable) -> None:
    fake = api([])
    with pytest.raises(ToolError, match=re.escape(server.CATALOGUE)):
        await server.build_catalogue().call_tool(
            "list_folders", {"account_id": "acc_1"}
        )
    assert fake.calls == []


async def test_server_status_runs() -> None:
    result = await server.build_catalogue(transport="stdio").call_tool(
        "server_status", {"details": True}
    )
    text = json.dumps(result, default=str)
    assert "transport: stdio" in text
    assert "token_set: no" in text


def test_main_serves_the_catalogue_without_a_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No token and no service: the start asks nothing."""
    monkeypatch.setenv("MAILBOX_MCP_CATALOGUE", "true")

    async def asked() -> set[str]:
        raise AssertionError("the catalogue asks the service nothing")

    served: list[object] = []
    monkeypatch.setattr(server, "allowed_operations", asked)
    monkeypatch.setattr(
        cli.transport, "serve_stdio", lambda built, token: served.append(built)
    )
    cli.main([])
    assert len(served) == 1


def test_main_refuses_the_catalogue_beside_a_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAILBOX_MCP_CATALOGUE", "true")
    monkeypatch.setenv("MAILBOX_SERVICE_TOKEN", "tok")
    with pytest.raises(SystemExit, match="Unset MAILBOX_SERVICE_TOKEN"):
        cli.main([])
