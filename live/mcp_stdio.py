"""Live check of the MCP server over stdio, the way Claude starts it.

    uv run python live/mcp_stdio.py

Starts a service of its own on a free port, with a throwaway database and
master key, adds the first two test accounts of ``live/.env`` through the
API, and makes a user that may only read them. Then it starts
``benethos-mailbox-mcp`` over stdio with that user's token and calls the
tools. A second user may also write: with it the check creates a folder in
the first test account, stars, moves and trashes the newest inbox message
there, and puts everything back as it was. A third user may write drafts:
it writes, replaces and deletes a reply draft. Nothing is sent. A fourth
user may send: it sends one mail twice with the same call, one draft and
one HTML mail, from the first test account to the second only, and
deletes them for good afterwards. Two more users check that a grant's
recipients and send limit stop a mail, again only between the test
accounts, and that the audit names each attempt. The throwaway database is
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
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import anyio
import httpx
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from register import register
from smoke import ENV_FILE, Run, accounts, read_env

from benethos_mailbox_api.data.secrets import cipher, encode_recovery

READ_TOOLS = {
    "list_accounts",
    "list_folders",
    "search_messages",
    "get_message",
    "get_attachment",
}
WRITE_TOOLS = READ_TOOLS | {"update_messages", "create_folder"}
DRAFT_TOOLS = READ_TOOLS | {
    "list_drafts",
    "create_draft",
    "update_draft",
    "delete_draft",
}


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


def user_token(
    client: httpx.Client,
    account_ids: list[str],
    allow: list[str],
    **constraints: Any,
) -> str:
    """A user with ``allow`` on the test accounts, and a token for it."""
    user = client.post(
        "/v1/users",
        json={
            "name": f"mcp live check {'+'.join(allow)}",
            "grants": [{"accounts": account_ids, "allow": allow, **constraints}],
        },
    ).json()
    created = client.post(f"/v1/users/{user['id']}/tokens", json={"name": "live"})
    return str(created.json()["token"])


def text_of(result: Any) -> str:
    return "".join(getattr(part, "text", "") for part in result.content)


@asynccontextmanager
async def mcp_session(url: str, token: str) -> AsyncIterator[ClientSession]:
    """``benethos-mailbox-mcp`` over stdio with ``token``."""
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
        yield session


async def check_tools(run: Run, url: str, token: str, emails: set[str]) -> None:
    async with mcp_session(url, token) as session:
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
        await check_pdf(run, session)
        refused = await session.call_tool(
            "get_message", {"account_id": "acc_unknown", "message_id": "msg_x"}
        )
        run.check(
            "an unknown account is a tool error, not a crash",
            bool(refused.is_error) and "not found" in text_of(refused),
        )


async def check_pdf(run: Run, session: ClientSession) -> None:
    """A PDF attachment, if the test accounts hold one, comes as PNG pages."""
    found = await session.call_tool(
        "search_messages", {"has_attachments": True, "limit": 20}
    )
    for summary in (found.structured_content or {}).get("messages", []):
        read = await session.call_tool(
            "get_message",
            {"account_id": summary["account_id"], "message_id": summary["id"]},
        )
        pdfs = [
            line.split()[1]
            for line in text_of(read).splitlines()
            if line.startswith("attachment:") and "application/pdf" in line
        ]
        if not pdfs:
            continue
        result = await session.call_tool(
            "get_attachment",
            {
                "account_id": summary["account_id"],
                "message_id": summary["id"],
                "attachment_id": pdfs[0],
            },
        )
        images = [p for p in result.content if p.type == "image"]
        run.check(
            "get_attachment hands a PDF over as PNG pages",
            not result.is_error
            and bool(images)
            and all(p.mime_type == "image/png" for p in images),
            f"{len(images)} pages",
        )
        return
    print("SKIP  no PDF attachment in the test accounts")


async def check_writing(
    run: Run, url: str, token: str, admin: httpx.Client, account_id: str
) -> None:
    """Folder, star, move and trash through the tools, then all put back."""
    folders_url = f"/v1/accounts/{account_id}/folders"
    inbox = next(f for f in admin.get(folders_url).json() if f.get("role") == "inbox")
    newest = admin.get(
        f"/v1/accounts/{account_id}/messages",
        params={"folder": inbox["id"], "limit": 1},
    ).json()["items"]
    if not newest:
        print("SKIP  no message in the inbox of the first test account")
        return
    message = newest[0]
    message_url = f"/v1/accounts/{account_id}/messages/{message['id']}"
    folder_id = None
    try:
        async with mcp_session(url, token) as session:
            tools = {tool.name for tool in (await session.list_tools()).tools}
            run.check(
                "a token that may write sees the write tools too",
                tools == WRITE_TOOLS,
                ", ".join(sorted(tools - READ_TOOLS)),
            )

            async def update(**changes: Any) -> dict[str, Any]:
                result = await session.call_tool(
                    "update_messages",
                    {
                        "account_id": account_id,
                        "message_ids": [message["id"]],
                        **changes,
                    },
                )
                found: dict[str, Any] = result.structured_content or {}
                if result.is_error:
                    found = {"error": text_of(result)}
                return found

            created = await session.call_tool(
                "create_folder",
                {"account_id": account_id, "name": f"mcp-live-{secrets.token_hex(4)}"},
            )
            folder_id = (created.structured_content or {}).get("id")
            run.check("create_folder", not created.is_error and bool(folder_id))

            starred = await update(starred=not message["starred"])
            now = admin.get(message_url).json()
            run.check(
                "update_messages stars",
                starred.get("done") == [message["id"]]
                and now["starred"] is not message["starred"],
                str(starred.get("error", "")),
            )
            await update(starred=message["starred"])

            if folder_id:
                moved = await update(move_to=folder_id)
                now = admin.get(message_url).json()
                run.check(
                    "update_messages moves into the new folder, the id stays",
                    moved.get("done") == [message["id"]]
                    and now.get("folder_ids") == [folder_id],
                    str(moved.get("error", "")),
                )

            trashed = await update(trash=True)
            now = admin.get(message_url).json()
            trash = next(
                (f for f in admin.get(folders_url).json() if f.get("role") == "trash"),
                {},
            )
            run.check(
                "update_messages trashes",
                trashed.get("done") == [message["id"]]
                and now.get("folder_ids") == [trash.get("id")],
                str(trashed.get("error", "")),
            )

            back = await update(move_to="inbox")
            now = admin.get(message_url).json()
            run.check(
                "update_messages moves back by role",
                back.get("done") == [message["id"]]
                and now.get("folder_ids") == [inbox["id"]],
                str(back.get("error", "")),
            )
    finally:
        # Whatever failed above: the message back in the inbox as it was.
        admin.patch(
            message_url,
            json={
                "folder_ids": [inbox["id"]],
                "starred": message["starred"],
                "unread": message["unread"],
            },
        )
        if folder_id:
            removed = admin.delete(f"{folders_url}/{folder_id}")
            run.check("the test folder removed again", removed.status_code == 204)


async def check_drafts(
    run: Run, url: str, token: str, admin: httpx.Client, account_id: str, to: str
) -> None:
    """A reply draft written, listed, replaced, read and deleted. Nothing is
    sent."""
    newest = admin.get(
        f"/v1/accounts/{account_id}/messages", params={"folder": "inbox", "limit": 1}
    ).json()["items"]
    if not newest:
        print("SKIP  no message in the inbox of the first test account")
        return
    original = newest[0]
    draft_id = None
    try:
        async with mcp_session(url, token) as session:
            tools = {tool.name for tool in (await session.list_tools()).tools}
            run.check(
                "a token with drafts sees the draft tools",
                tools == DRAFT_TOOLS,
                ", ".join(sorted(tools - READ_TOOLS)),
            )
            created = await session.call_tool(
                "create_draft",
                {
                    "account_id": account_id,
                    "text": "mailbox-api MCP draft check",
                    "original_id": original["id"],
                },
            )
            draft = created.structured_content or {}
            draft_id = draft.get("id")
            run.check(
                "create_draft writes a reply draft",
                not created.is_error
                and str(draft.get("subject", "")).startswith("Re:"),
                text_of(created) if created.is_error else "",
            )
            listed = await session.call_tool("list_drafts", {"account_id": account_id})
            run.check(
                "list_drafts has it",
                draft_id
                in [
                    d["id"] for d in (listed.structured_content or {}).get("drafts", [])
                ],
            )
            replaced = await session.call_tool(
                "update_draft",
                {
                    "account_id": account_id,
                    "draft_id": draft_id,
                    "to": [to],
                    "subject": "mailbox-api MCP draft check",
                    "text": "second version",
                },
            )
            read = await session.call_tool(
                "get_message", {"account_id": account_id, "message_id": draft_id}
            )
            run.check(
                "update_draft replaces it, the id stays",
                not replaced.is_error
                and (replaced.structured_content or {}).get("id") == draft_id
                and "second version" in text_of(read),
                text_of(replaced) if replaced.is_error else "",
            )
            refused = await session.call_tool(
                "delete_draft", {"account_id": account_id, "draft_id": original["id"]}
            )
            run.check(
                "delete_draft does not reach other mail",
                bool(refused.is_error) and "404" in text_of(refused),
            )
            deleted = await session.call_tool(
                "delete_draft", {"account_id": account_id, "draft_id": draft_id}
            )
            run.check("delete_draft", not deleted.is_error)
            if not deleted.is_error:
                draft_id = None
    finally:
        if draft_id:
            admin.delete(f"/v1/accounts/{account_id}/drafts/{draft_id}")


def arrived(admin: httpx.Client, account_id: str, subject: str) -> list[dict[str, Any]]:
    """The messages with ``subject`` in the account, once one is there."""
    for _ in range(20):
        page = admin.get(
            f"/v1/accounts/{account_id}/messages", params={"q": subject, "limit": 10}
        ).json()
        found = [m for m in page.get("items", []) if m.get("subject") == subject]
        if found:
            return found
        time.sleep(3)
    return []


async def check_sending(
    run: Run,
    url: str,
    token: str,
    admin: httpx.Client,
    ids: list[str],
    to: str,
) -> None:
    """From the first test account to the second only: a mail sent twice
    with the same call arrives once, a draft is sent. Both are deleted for
    good afterwards, in the inbox and in the sent folder."""
    sender, receiver = ids
    subject = f"mailbox-api MCP send check {secrets.token_hex(4)}"
    subjects = [subject, f"{subject} draft", f"{subject} html"]
    try:
        async with mcp_session(url, token) as session:
            tools = {tool.name for tool in (await session.list_tools()).tools}
            run.check(
                "a token with send sees the send tools",
                {"send_message", "send_draft"} <= tools,
            )
            call = {"account_id": sender, "to": [to], "subject": subject, "text": "1"}
            first = await session.call_tool("send_message", call)
            again = await session.call_tool("send_message", call)
            header = (first.structured_content or {}).get("message_id_header")
            run.check(
                "send_message sends, the same call again answers the first result",
                not first.is_error
                and bool(header)
                and (again.structured_content or {}).get("message_id_header") == header,
                text_of(first) if first.is_error else "",
            )
            draft = await session.call_tool(
                "create_draft",
                {"account_id": sender, "to": [to], "subject": subjects[1], "text": "2"},
            )
            draft_id = (draft.structured_content or {}).get("id")
            sent = await session.call_tool(
                "send_draft", {"account_id": sender, "draft_id": draft_id}
            )
            run.check(
                "send_draft sends the draft",
                not sent.is_error and (sent.structured_content or {}).get("sent"),
                text_of(sent) if sent.is_error else "",
            )
            html = await session.call_tool(
                "send_message",
                {
                    "account_id": sender,
                    "to": [to],
                    "subject": subjects[2],
                    "html": '<p>Hello <b style="color:#0a6">HTML</b></p>',
                },
            )
            run.check("send_message sends HTML", not html.is_error)
        received = arrived(admin, receiver, subject)
        run.check(
            "the mail arrived once", len(received) == 1, f"{len(received)} copies"
        )
        run.check("the sent draft arrived", bool(arrived(admin, receiver, subjects[1])))
        found = arrived(admin, receiver, subjects[2])
        body = (
            admin.get(f"/v1/accounts/{receiver}/messages/{found[0]['id']}").json()
            if found
            else {}
        )
        run.check(
            "the HTML mail arrived with both parts, the text made from the HTML",
            "<b" in (body.get("html_body") or "")
            and (body.get("text_body") or "").strip() == "Hello HTML",
        )
    finally:
        delete_test_mails(admin, ids, subjects)


def delete_test_mails(admin: httpx.Client, ids: list[str], subjects: list[str]) -> None:
    """The mails with these subjects, for good: in the second test account's
    inbox and the first one's sent folder."""
    sender, receiver = ids
    removed = 0
    for account_id, folder in ((receiver, "inbox"), (sender, "sent")):
        for title in subjects:
            page = admin.get(
                f"/v1/accounts/{account_id}/messages",
                params={"folder": folder, "q": title, "limit": 10},
            ).json()
            for message in page.get("items", []):
                if message.get("subject") == title:
                    admin.delete(
                        f"/v1/accounts/{account_id}/messages/{message['id']}",
                        params={"permanent": True},
                    )
                    removed += 1
    print(f"      cleanup: {removed} test mail(s) deleted for good")


async def check_constraints(
    run: Run,
    url: str,
    admin: httpx.Client,
    ids: list[str],
    emails: list[str],
) -> None:
    """Grants that narrow sending, and the audit. Only between the test
    accounts: the recipient that must be refused is the second test account
    too, so a failing check still sends nowhere else."""
    sender, _ = ids
    own, other = emails
    subject = f"mailbox-api MCP limit check {secrets.token_hex(4)}"
    subjects = [subject, f"{subject} 2"]
    only_self = user_token(admin, ids, ["send"], recipients=[own])
    once = user_token(admin, ids, ["send"], recipients=[other], max_sends_per_day=1)
    try:
        async with mcp_session(url, only_self) as session:
            refused = await session.call_tool(
                "send_message",
                {"account_id": sender, "to": [other], "subject": subject, "text": "x"},
            )
            run.check(
                "a grant's recipients stop a mail to anyone else",
                bool(refused.is_error) and "recipient_not_allowed" in text_of(refused),
                "refused" if refused.is_error else "sent",
            )
        async with mcp_session(url, once) as session:
            results = []
            for title in subjects:
                results.append(
                    await session.call_tool(
                        "send_message",
                        {
                            "account_id": sender,
                            "to": [other],
                            "subject": title,
                            "text": "x",
                        },
                    )
                )
            first, second = results
            run.check(
                "a grant's send limit stops the second mail of the day",
                not first.is_error
                and bool(second.is_error)
                and "send_limit_reached" in text_of(second),
                "stopped" if second.is_error else "sent",
            )
        audit = admin.get(f"/v1/accounts/{sender}/sends", params={"limit": 3}).json()
        outcomes = [record["outcome"] for record in audit.get("items", [])]
        run.check(
            "the audit names every attempt, newest first",
            outcomes == ["denied", "sent", "denied"],
            ", ".join(outcomes),
        )
    finally:
        delete_test_mails(admin, ids, subjects)


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
            token = user_token(client, ids, ["mail.read"])
            writer = user_token(client, ids, ["mail.read", "mail.write"])
            emails = {a["email"].lower() for a in test_accounts}
            print("\n== the MCP server over stdio, reading")
            anyio.run(check_tools, run, url, token, emails)
            print("\n== the MCP server over stdio, writing")
            anyio.run(check_writing, run, url, writer, client, ids[0])
            drafter = user_token(client, ids, ["mail.read", "drafts"])
            print("\n== the MCP server over stdio, drafts")
            anyio.run(
                check_drafts,
                run,
                url,
                drafter,
                client,
                ids[0],
                test_accounts[1]["email"],
            )
            # Sends from the first test account to the second, nowhere else.
            sender = user_token(client, ids, ["mail.read", "drafts", "send"])
            print("\n== the MCP server over stdio, sending")
            anyio.run(
                check_sending, run, url, sender, client, ids, test_accounts[1]["email"]
            )
            print("\n== grants that narrow sending, and the audit")
            anyio.run(
                check_constraints,
                run,
                url,
                client,
                ids,
                [a["email"] for a in test_accounts],
            )
    finally:
        process.terminate()
        process.wait(timeout=10)
        shutil.rmtree(Path(data_dir), ignore_errors=True)
    print(f"\n{run.failures} failed" if run.failures else "\nall passed")
    return 1 if run.failures else 0


if __name__ == "__main__":
    sys.exit(main())
