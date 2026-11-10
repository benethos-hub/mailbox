"""docs/mcp-tools.json: every tool as a client lists it, checked in so a
change to a tool's description, schema or hints shows in review."""

from __future__ import annotations

import json
from pathlib import Path

import anyio
import pytest

from benethos_mailbox_mcp import cli, server
from benethos_mailbox_mcp.tools import TOOLS

COMMITTED = Path(__file__).resolve().parents[3] / "docs" / "mcp-tools.json"


async def test_the_committed_tools_are_the_codes() -> None:
    assert COMMITTED.read_text(encoding="utf-8") == await server.tools_json(), (
        "docs/mcp-tools.json is stale, regenerate it with "
        "`uv run benethos-mailbox-mcp --list-tools > docs/mcp-tools.json`"
    )


async def test_it_holds_every_tool_with_its_hints() -> None:
    listed = json.loads(await server.tools_json())
    assert [tool["name"] for tool in listed] == [tool.fn.__name__ for tool in TOOLS]
    assert all("readOnlyHint" in tool["annotations"] for tool in listed)


def test_list_tools_prints_them_without_a_service(
    capsys: pytest.CaptureFixture[str],
) -> None:
    cli.main(["--list-tools"])
    assert capsys.readouterr().out == anyio.run(server.tools_json)
