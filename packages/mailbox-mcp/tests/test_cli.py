"""The command line: options, the start over stdio, the log."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable

import pytest

from benethos_mailbox_client import MailboxClient
from benethos_mailbox_common.log import redact
from benethos_mailbox_mcp import __version__, cli, server
from benethos_mailbox_mcp import tools as catalogue
from benethos_mailbox_mcp.errors import ToolError

# What the token may do, as the start reads it.
ALLOWED = {"get_message", "list_folders"}


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        cli.main(["--version"])
    assert __version__ in capsys.readouterr().out


def test_main_runs_stdio_with_the_allowed_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAILBOX_SERVICE_TOKEN", "tok")

    async def operations() -> set[str]:
        return ALLOWED

    runs: list[tuple[set[str], float, str]] = []

    class Recorded:
        def __init__(self, allowed: set[str], every: float) -> None:
            self.allowed = allowed
            self.every = every

        def run(self, transport: str) -> None:
            runs.append((self.allowed, self.every, transport))

    monkeypatch.setattr(server, "allowed_operations", operations)
    monkeypatch.setattr(
        server,
        "build_server",
        lambda ops, connect=None, every=0, **_: Recorded(set(ops), every),
    )
    cli.main([])
    assert runs == [(ALLOWED, 60, "stdio")]


def test_the_log_names_no_request_url(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    for name in ("httpx", "httpcore"):
        monkeypatch.setattr(logging.getLogger(name), "level", logging.NOTSET)
    cli.configure_logging("INFO")
    with caplog.at_level(logging.INFO):
        logging.getLogger("httpx").info("HTTP Request: GET /v1/messages?q=invoice")
    assert "invoice" not in caplog.text
    assert logging.getLogger("httpx").getEffectiveLevel() == logging.WARNING


def test_main_without_the_service(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAILBOX_SERVICE_TOKEN", "tok")

    async def unreachable() -> set[str]:
        raise ToolError("mailbox-service is not reachable")

    monkeypatch.setattr(server, "allowed_operations", unreachable)
    with pytest.raises(SystemExit, match="not reachable"):
        cli.main([])


def test_main_masks_both_tokens_in_every_line(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neither the service's token nor the bearer token reaches a line."""
    monkeypatch.setenv("MAILBOX_SERVICE_TOKEN", "the-token-of-the-service")
    monkeypatch.setenv("MAILBOX_MCP_BEARER_TOKEN", "the-bearer-token-of-mcp")

    async def unreachable() -> set[str]:
        raise ToolError("mailbox-service is not reachable")

    monkeypatch.setattr(server, "allowed_operations", unreachable)
    with pytest.raises(SystemExit):
        cli.main([])
    text = redact.redact("the-token-of-the-service, the-bearer-token-of-mcp")
    assert text == "***, ***"


def test_main_without_a_token() -> None:
    with pytest.raises(SystemExit, match="MAILBOX_SERVICE_TOKEN is not set"):
        cli.main([])


def test_the_start_leaves_no_client_behind(monkeypatch: pytest.MonkeyPatch) -> None:
    """The start runs in an event loop of its own. A client made there would
    carry connections of a closed loop into the server's. The server gets
    the environment as it was read at the start."""

    monkeypatch.setenv("MAILBOX_SERVICE_TOKEN", "tok")
    made: list[MailboxClient] = []
    built: list[Callable[[], MailboxClient]] = []

    async def operations() -> set[str]:
        made.append(catalogue.client())
        return ALLOWED

    def build(
        ops: set[str],
        connect: Callable[[], MailboxClient],
        every: float,
        **_: object,
    ) -> object:
        built.append(connect)
        return type("S", (), {"run": lambda self, transport: None})()

    monkeypatch.setattr(server, "allowed_operations", operations)
    monkeypatch.setattr(server, "build_server", build)
    cli.main([])
    assert made[0]._http.is_closed
    with pytest.raises(RuntimeError):
        catalogue.client()
    monkeypatch.delenv("MAILBOX_SERVICE_TOKEN")
    assert built[0]().base_url == "http://127.0.0.1:8080"


def test_the_start_names_the_service_and_the_tools(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    async def operations() -> set[str]:
        return {"list_accounts"}

    monkeypatch.setenv("MAILBOX_SERVICE_URL", "http://127.0.0.1:8080")
    monkeypatch.setenv("MAILBOX_SERVICE_TOKEN", "tok")
    monkeypatch.setattr(server, "allowed_operations", operations)
    monkeypatch.setattr(
        server,
        "build_server",
        lambda ops, connect=None, every=0, **_: type(
            "S", (), {"run": lambda self, transport: None}
        )(),
    )
    with caplog.at_level(logging.INFO):
        cli.main([])
    assert (
        "serving 2 tools over stdio for mailbox-service at "
        "http://127.0.0.1:8080: list_accounts, server_status" in caplog.text
    )


def test_the_mcp_library_logs_from_warning_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(logging.getLogger("mcp"), "level", logging.NOTSET)
    cli.configure_logging("INFO")
    assert logging.getLogger("mcp").getEffectiveLevel() == logging.WARNING


def test_every_line_is_written_as_the_service_writes_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The lines of ``benethos_mailbox_common.log.lines``: the time in ISO 8601,
    local, to the millisecond, with the offset, and a noted secret
    masked."""
    root = logging.getLogger()
    monkeypatch.setattr(root, "handlers", [])
    monkeypatch.setattr(root, "level", root.level)
    cli.configure_logging("INFO")
    [handler] = root.handlers
    redact.note("a-token-in-a-line")
    record = logging.makeLogRecord(
        {"created": 1790590342.1239, "name": "benethos_mailbox_mcp.server"}
    )
    record.levelname = "INFO"
    record.msg = "started with a-token-in-a-line"
    assert re.fullmatch(
        r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.123[+-]\d\d:\d\d INFO     "
        r"benethos_mailbox_mcp\.server: started with \*\*\*",
        handler.format(record),
    )
