"""server_status: the core from memory, without a request, the same shape
both ways, offered whatever the token may do."""

from __future__ import annotations

import re
import sys
from importlib.metadata import version

import httpx
import pytest

from benethos_mailbox_client import MailboxClient
from benethos_mailbox_mcp import __version__, server
from benethos_mailbox_mcp.tools import Running, status

from ..rights_helpers import ME, READ, Connected, Service, connected, following

CORE = ["name", "version", "transport", "python", "mcp", "uptime_seconds"]
UPSTREAM = [
    "reachable",
    "checked_seconds_ago",
    "token_set",
    "service_version",
    "versions_match",
    "token_accepted",
    "tools_offered",
]


async def answer_of(client: Connected, details: bool | None = None) -> str:
    arguments = {} if details is None else {"details": details}
    result = await client.session.call_tool("server_status", arguments)
    assert not result.is_error
    assert result.structured_content is None
    return "".join(getattr(part, "text", "") for part in result.content)


def fields(text: str) -> dict[str, str]:
    """Each ``key: value`` line, its indent kept in the key."""
    found = {}
    for line in text.splitlines():
        key, _, value = line.partition(":")
        found[key] = value.strip()
    return found


async def test_the_core_by_name_and_order_without_a_request() -> None:
    service = Service(ME)
    async with connected(following(service, READ, every=0)) as client:
        asked = service.asked
        text = await answer_of(client)
    assert service.asked == asked
    assert list(fields(text)) == CORE
    python = sys.version_info
    assert fields(text) == {
        "name": "benethos-mailbox-mcp",
        "version": __version__,
        "transport": "stdio",
        "python": f"{python.major}.{python.minor}.{python.micro}",
        "mcp": version("mcp"),
        "uptime_seconds": fields(text)["uptime_seconds"],
    }
    assert re.fullmatch(r"\d+", fields(text)["uptime_seconds"])


async def test_details_add_the_upstream_block_and_ask_no_one() -> None:
    """Passive: what the server's own requests showed, nothing asked for
    the answer."""
    service = Service(ME)
    async with connected(following(service, READ, every=0)) as client:
        asked = service.asked
        text = await answer_of(client, details=True)
        assert await answer_of(client, details=False) == await answer_of(client)
    assert service.asked == asked
    lines = text.splitlines()
    assert [line.split(":")[0] for line in lines[: len(CORE)]] == CORE
    assert lines[len(CORE) : len(CORE) + 2] == ["details:", "  upstream:"]
    below = lines[len(CORE) + 2 :]
    assert [line.partition(":")[0] for line in below] == [
        f"    {key}" for key in UPSTREAM
    ]


async def test_the_tools_offered_leave_the_status_tool_out() -> None:
    async with connected(following(Service(ME), READ, every=0)) as client:
        offered = fields(await answer_of(client, details=True))["    tools_offered"]
        tools = await client.tools()
    assert offered.split(", ") == [name for name in tools if name != "server_status"]


async def test_it_is_offered_without_any_right() -> None:
    tools = await server.build_server([]).list_tools()
    assert [tool.name for tool in tools] == ["list_accounts", "server_status"]
    [found] = [tool for tool in tools if tool.name == "server_status"]
    assert list(found.input_schema["properties"]) == ["details"]
    assert found.input_schema["properties"]["details"]["default"] is False
    assert len((found.description or "").split(". ")) == 2


def test_the_answer_of_a_server_that_saw_nothing() -> None:
    running = Running("streamable-http", started=100.0)
    text = status.answer(running, True, now=142.9)
    found = {key.strip(): value for key, value in fields(text).items()}
    assert (found["transport"], found["uptime_seconds"]) == ("streamable-http", "42")
    assert {key: found[key] for key in UPSTREAM} == {
        "reachable": "unknown",
        "checked_seconds_ago": "never",
        "token_set": "no",
        "service_version": "unknown",
        "versions_match": "unknown",
        "token_accepted": "unknown",
        "tools_offered": "none",
    }


async def test_outside_a_server_it_answers_all_the_same() -> None:
    result = await status.server_status(details=True)
    text = "".join(getattr(part, "text", "") for part in result.content)
    assert fields(text)["transport"] == "unknown"


@pytest.mark.parametrize("details", [False, True])
async def test_no_part_of_the_token_shows(details: bool) -> None:
    secret = "tok_" + "9f3c1a7e5b2d4f60" * 2
    service = Service(ME)

    def connect() -> MailboxClient:
        return MailboxClient(
            "https://mail.test", secret, transport=httpx.MockTransport(service)
        )

    async with connected(server.build_server(READ, connect)) as client:
        text = await answer_of(client, details)
    windows = {secret[n : n + 6] for n in range(len(secret) - 5)}
    assert not any(window in text for window in windows)
