"""Live check of the MCP server over stdio, the way Claude starts it.

    uv run python live/mcp_stdio.py

Starts a service of its own on a free port, with a throwaway database and
master key, adds the first two test accounts of ``live/.env`` through the
API, and makes a user that may only read them. Then it starts
``benethos-mailbox-mcp`` over stdio with that user's token and calls the
tools. Nothing in the mailboxes is written; the throwaway database is
deleted at the end. Credentials and mail content are never printed.
"""

from __future__ import annotations

import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import anyio
import httpx
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from register import register
from smoke import ENV_FILE, Run, accounts, read_env

from benethos_mailbox_api.data.secrets import cipher, encode_recovery

READ_TOOLS = {"list_accounts", "list_folders", "search_messages", "get_message"}


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def service_env(data_dir: str, port: int, admin_key: str) -> dict[str, str]:
    return {
        **os.environ,
        "MAILBOX_API_DATA_DIR": data_dir,
        "MAILBOX_API_STORAGE": "sqlite",
        "MAILBOX_API_KEY_PROVIDER": "env",
        "MAILBOX_API_MASTER_KEY": encode_recovery(cipher.new_key()),
        "MAILBOX_API_KEY": admin_key,
        "MAILBOX_API_HOST": "127.0.0.1",
        "MAILBOX_API_PORT": str(port),
        "MAILBOX_API_SYNC_INTERVAL": "0",
        "MAILBOX_API_SYNC_IDLE": "false",
    }


def start_service(env: dict[str, str], url: str) -> subprocess.Popen[bytes]:
    command = shutil.which("benethos-mailbox-api")
    if command is None:
        sys.exit("benethos-mailbox-api not found: run this with uv run")
    subprocess.run([command, "keys", "init"], env=env, check=True, capture_output=True)
    process = subprocess.Popen(
        [command, "serve"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
    )
    for _ in range(60):
        try:
            if httpx.get(f"{url}/health", timeout=1).status_code == 200:
                return process
        except httpx.TransportError:
            time.sleep(0.5)
    process.terminate()
    sys.exit("the service did not start")


def reader_token(client: httpx.Client, account_ids: list[str]) -> str:
    """A user that may only read the test accounts, and a token for it."""
    user = client.post(
        "/v1/users",
        json={
            "name": "mcp live check",
            "grants": [{"accounts": account_ids, "allow": ["mail.read"]}],
        },
    ).json()
    created = client.post(f"/v1/users/{user['id']}/tokens", json={"name": "live"})
    return str(created.json()["token"])


def text_of(result: Any) -> str:
    return "".join(getattr(part, "text", "") for part in result.content)


async def check_tools(run: Run, url: str, token: str, emails: set[str]) -> None:
    command = shutil.which("benethos-mailbox-mcp")
    if command is None:
        sys.exit("benethos-mailbox-mcp not found: run this with uv run")
    params = StdioServerParameters(
        command=command,
        env={**os.environ, "MAILBOX_API_URL": url, "MAILBOX_API_TOKEN": token},
    )
    async with (
        stdio_client(params) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        tools = {tool.name for tool in (await session.list_tools()).tools}
        run.check(
            "a read-only token sees the read tools, nothing more",
            tools == READ_TOOLS,
            ", ".join(sorted(tools)),
        )

        listed = await session.call_tool("list_accounts", {})
        found = listed.structured_content or {}
        accounts_seen = found.get("result", [])
        run.check(
            "list_accounts names both test accounts, may read",
            {a["email"].lower() for a in accounts_seen} == emails
            and all(a["can"] == ["read"] for a in accounts_seen),
            f"{len(accounts_seen)} accounts",
        )

        searched = await session.call_tool(
            "search_messages", {"folder": "inbox", "limit": 5}
        )
        page = searched.structured_content or {}
        messages = page.get("messages", [])
        run.check(
            "search_messages across accounts",
            not searched.is_error and bool(messages),
            f"{len(messages)} messages",
        )
        if messages:
            first = messages[0]
            read = await session.call_tool(
                "get_message",
                {"account_id": first["account_id"], "message_id": first["id"]},
            )
            body = text_of(read)
            run.check(
                "get_message answers the mail inside the foreign-content marker",
                not read.is_error
                and "<mail-content" in body
                and "</mail-content>" in body,
                f"{len(body)} characters",
            )
        refused = await session.call_tool(
            "get_message", {"account_id": "acc_unknown", "message_id": "msg_x"}
        )
        run.check(
            "an unknown account is a tool error, not a crash",
            bool(refused.is_error) and "not found" in text_of(refused),
        )


def main() -> int:
    env = read_env(ENV_FILE)
    test_accounts = accounts(env)[:2]
    run = Run()
    port = free_port()
    url = f"http://127.0.0.1:{port}"
    admin_key = secrets.token_urlsafe(32)
    data_dir = tempfile.mkdtemp(prefix="mailbox-mcp-live-")
    process = start_service(service_env(data_dir, port, admin_key), url)
    try:
        with httpx.Client(
            base_url=url, headers={"Authorization": f"Bearer {admin_key}"}, timeout=60
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
            token = reader_token(client, ids)
        emails = {a["email"].lower() for a in test_accounts}
        print("\n== the MCP server over stdio")
        anyio.run(check_tools, run, url, token, emails)
    finally:
        process.terminate()
        process.wait(timeout=10)
        shutil.rmtree(Path(data_dir), ignore_errors=True)
    print(f"\n{run.failures} failed" if run.failures else "\nall passed")
    return 1 if run.failures else 0


if __name__ == "__main__":
    sys.exit(main())
