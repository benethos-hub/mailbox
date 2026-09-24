from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from benethos_mailbox_mcp import __version__, server
from benethos_mailbox_mcp.client import MailboxApiClient
from benethos_mailbox_mcp.errors import ToolError


async def test_tools_registered() -> None:
    names = {tool.name for tool in await server.mcp.list_tools()}
    assert names == {"list_accounts"}


async def test_list_accounts_goes_through_rest(make_client: Callable) -> None:
    make_client(lambda _: httpx.Response(200, json=[{"id": "acc_1"}]))
    assert await server.list_accounts() == [{"id": "acc_1"}]


async def test_errors_are_tool_errors(make_client: Callable) -> None:
    make_client(
        lambda _: httpx.Response(
            401, json={"error": {"code": "unauthorized", "message": "wrong token"}}
        )
    )
    with pytest.raises(ToolError, match="wrong token"):
        await server.list_accounts()


def test_client_is_created_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "_client", None)
    first = server.client()
    assert isinstance(first, MailboxApiClient)
    assert server.client() is first


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        server.main(["--version"])
    assert __version__ in capsys.readouterr().out


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        ([], ("stdio", {})),
        (
            ["--transport", "streamable-http", "--port", "9001"],
            ("streamable-http", {"host": "127.0.0.1", "port": 9001}),
        ),
    ],
)
def test_main_selects_transport(
    monkeypatch: pytest.MonkeyPatch, argv: list[str], expected: tuple
) -> None:
    calls: list[tuple] = []
    monkeypatch.setattr(
        server.mcp, "run", lambda transport, **kw: calls.append((transport, kw))
    )
    server.main(argv)
    assert calls == [expected]
