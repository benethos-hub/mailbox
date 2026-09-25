"""Live check of the MCP server over streamable HTTP, behind its bearer guard.

    uv run python live/mcp_http.py

Starts a service of its own with a throwaway database, as mcp_stdio.py
does, adds the first two test accounts and makes a user that may only read
them. Then it starts ``benethos-mailbox-mcp --transport streamable-http`` on
a free port with that user's API token and a bearer token of its own. It
checks that a request without the bearer token is refused, and that the
tools answer with it. Nothing in the mailboxes is written. Credentials and
mail content are never printed.
"""

from __future__ import annotations

import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import anyio
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client
from mcp_stdio import (
    READ_TOOLS,
    free_port,
    service_env,
    start_service,
    user_token,
)
from register import register
from smoke import ENV_FILE, Run, accounts, read_env


def start_mcp(
    api_url: str, api_token: str, bearer: str, port: int
) -> subprocess.Popen[bytes]:
    command = shutil.which("benethos-mailbox-mcp")
    if command is None:
        sys.exit("benethos-mailbox-mcp not found: run this with uv run")
    env = {
        **os.environ,
        "MAILBOX_SERVICE_URL": api_url,
        "MAILBOX_SERVICE_TOKEN": api_token,
        "MAILBOX_MCP_BEARER_TOKEN": bearer,
    }
    process = subprocess.Popen(
        [command, "--transport", "streamable-http", "--port", str(port)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(60):
        try:
            httpx.get(f"http://127.0.0.1:{port}/mcp", timeout=1)
            return process
        except httpx.TransportError:
            time.sleep(0.5)
    process.terminate()
    sys.exit("the MCP server did not start")


async def check_http(run: Run, url: str, bearer: str, emails: set[str]) -> None:
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "live", "version": "0"},
        },
    }
    headers = {"Accept": "application/json, text/event-stream"}
    async with httpx.AsyncClient() as plain:
        refused = await plain.post(url, json=body, headers=headers)
        wrong = await plain.post(
            url, json=body, headers={**headers, "Authorization": "Bearer wrong"}
        )
    run.check(
        "without the bearer token: 401",
        refused.status_code == wrong.status_code == 401,
        f"{refused.status_code}, {wrong.status_code}",
    )
    client = create_mcp_http_client(headers={"Authorization": f"Bearer {bearer}"})
    async with (
        client,
        streamable_http_client(url, http_client=client) as streams,
        ClientSession(streams[0], streams[1]) as session,
    ):
        await session.initialize()
        tools = {tool.name for tool in (await session.list_tools()).tools}
        run.check(
            "with it: the read tools of the server's user",
            tools == READ_TOOLS,
            ", ".join(sorted(tools)),
        )
        listed = await session.call_tool("list_accounts", {})
        found = (listed.structured_content or {}).get("result", [])
        run.check(
            "list_accounts over HTTP",
            {a["email"].lower() for a in found} == emails,
            f"{len(found)} accounts",
        )
        searched = await session.call_tool(
            "search_messages", {"folder": "inbox", "limit": 3}
        )
        run.check(
            "search_messages over HTTP",
            not searched.is_error,
            f"{len((searched.structured_content or {}).get('messages', []))} messages",
        )


def main() -> int:
    env = read_env(ENV_FILE)
    test_accounts = accounts(env)[:2]
    run = Run()
    api_port, mcp_port = free_port(), free_port()
    api_url = f"http://127.0.0.1:{api_port}"
    admin_key = secrets.token_urlsafe(32)
    bearer = secrets.token_urlsafe(32)
    data_dir = tempfile.mkdtemp(prefix="mailbox-mcp-http-")
    service = start_service(service_env(data_dir, api_port, admin_key), api_url)
    mcp = None
    try:
        with httpx.Client(
            base_url=api_url,
            headers={"Authorization": f"Bearer {admin_key}"},
            timeout=60,
        ) as client:
            ids = []
            for account in test_accounts:
                account_id, outcome = register(client, env, account)
                if run.check(
                    f"account {len(ids) + 1} in the service",
                    account_id is not None,
                    outcome,
                ):
                    ids.append(str(account_id))
            if len(ids) != len(test_accounts):
                return 1
            token = user_token(client, ids, ["mail.read"])
        mcp = start_mcp(api_url, token, bearer, mcp_port)
        print("\n== the MCP server over streamable HTTP")
        anyio.run(
            check_http,
            run,
            f"http://127.0.0.1:{mcp_port}/mcp",
            bearer,
            {a["email"].lower() for a in test_accounts},
        )
    finally:
        for process in (mcp, service):
            if process is not None:
                process.terminate()
                process.wait(timeout=10)
        shutil.rmtree(Path(data_dir), ignore_errors=True)
    print(f"\n{run.failures} failed" if run.failures else "\nall passed")
    return 1 if run.failures else 0


if __name__ == "__main__":
    sys.exit(main())
