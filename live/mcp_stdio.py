"""Live check of the MCP server over stdio, the way Claude starts it.

    uv run python live/mcp_stdio.py

Starts a service of its own on a free port, with a throwaway database and
master key, adds the first two test accounts of ``live/.env`` through the
API, and makes a user that may only read them. Then it starts
``benethos-mailbox-mcp`` over stdio with that user's token and calls the
tools, the conversation of a search hit among them. A second user may
also write: with it the check creates and renames
a folder in the first test account, adds and takes off a keyword, stars,
moves and trashes the newest inbox message there, and puts everything
back as it was. A label is refused there. whats_new must name those
changes. A third user may write drafts: it writes a reply draft without
the quote, with a file and a reply-to, replaces it with the file taken
from the stored draft, and deletes it. Nothing is sent. A fourth
user may send: it sends one mail twice with the same call, one draft and
one HTML mail, from the first test account to the second only, and
deletes them for good afterwards. Two more users check that a grant's
recipients and send limit stop a mail, again only between the test
accounts, and that the audit names each attempt. The throwaway database is
deleted at the end. Credentials and mail content are never printed.
"""

from __future__ import annotations

import base64
import sys
from typing import Any

import anyio
from checks.accounts import accounts, read_env, register_all
from checks.admin import user_token
from checks.mcp_sending import check_constraints, check_sending
from checks.mcp_session import READ_TOOLS, mcp_session, text_of
from checks.mcp_writing import check_writing
from checks.run import Run
from checks.service import throwaway_service
from mcp import ClientSession

from benethos_mailbox_client import SyncMailboxClient

DRAFT_TOOLS = READ_TOOLS | {
    "list_drafts",
    "create_draft",
    "update_draft",
    "delete_draft",
}


async def check_folders(run: Run, url: str, token: str, account_id: str) -> None:
    """A grant with ``folders`` (PERMISSIONS.md 8.5): the inbox alone.
    Read-only."""
    async with mcp_session(url, token) as session:
        listed = await session.call_tool("list_folders", {"account_id": account_id})
        found = listed.structured_content or {}
        roles = [f.get("role") for f in found.get("result", [])]
        run.check(
            "list_folders shows the inbox alone",
            not listed.is_error and roles == ["inbox"],
            ", ".join(str(r) for r in roles),
        )
        searched = await session.call_tool(
            "search_messages", {"folder": "archive", "limit": 5}
        )
        page = searched.structured_content or {}
        run.check(
            "search_messages finds nothing in the archive",
            not searched.is_error and not page.get("messages"),
            f"{len(page.get('messages', []))} messages",
        )


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
            await check_thread(run, session, first)
        await check_pdf(run, session)
        refused = await session.call_tool(
            "get_message", {"account_id": "acc_unknown", "message_id": "msg_x"}
        )
        run.check(
            "an unknown account is a tool error, not a crash",
            bool(refused.is_error) and "not found" in text_of(refused),
        )


async def check_thread(run: Run, session: ClientSession, hit: dict[str, Any]) -> None:
    """The conversation of a search hit, each mail marked as foreign."""
    found = await session.call_tool(
        "get_thread", {"account_id": hit["account_id"], "message_id": hit["id"]}
    )
    said = text_of(found)
    run.check(
        "get_thread reads the conversation of a search hit, marked as foreign",
        not found.is_error
        and f'source="{hit["account_id"]}/{hit["id"]}"' in said
        and f"thread: {hit.get('thread_id')}" in said,
        f"{said.count('<mail-content')} mail(s)",
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


async def check_drafts(
    run: Run, url: str, token: str, admin: SyncMailboxClient, account_id: str, to: str
) -> None:
    """A reply draft written, listed, replaced, read and deleted. Nothing is
    sent."""
    newest = admin.list_messages(account_id, folder="inbox", limit=1).items
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
                    "text": "mailbox-service MCP draft check",
                    "original_id": original.id,
                    "quote": False,
                    "reply_to": [to],
                    "attachments": [
                        {
                            "filename": "mcp-live.txt",
                            "content_type": "text/plain",
                            "data": base64.b64encode(b"mcp live check").decode(),
                        }
                    ],
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
            stored = admin.get_message(account_id, draft_id) if draft_id else None
            run.check(
                "without the quote, with a file and a reply-to, and it answers",
                stored is not None
                and "wrote:" not in (stored.text_body or "")
                and [a.filename for a in stored.attachments] == ["mcp-live.txt"]
                and [a.email.lower() for a in stored.reply_to] == [to.lower()]
                and stored.reference is not None
                and stored.reference.message_id == original.id,
            )
            attached = stored.attachments[0].id if stored and stored.attachments else ""
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
                    "subject": "mailbox-service MCP draft check",
                    "text": "second version",
                    "original_id": original.id,
                    "quote": False,
                    "attach_from": [
                        {"message_id": draft_id, "attachment_id": attached}
                    ],
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
            run.check(
                "attach_from takes the file of a stored mail, the link stays",
                "mcp-live.txt" in text_of(read)
                and f"answers: {original.id} (reply)" in text_of(read),
            )
            refused = await session.call_tool(
                "delete_draft", {"account_id": account_id, "draft_id": original.id}
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
            admin.delete_draft(account_id, draft_id)


def main() -> int:
    env = read_env()
    test_accounts = accounts(env)[:2]
    run = Run()
    with (
        throwaway_service("mailbox-mcp-live-") as service,
        service.mailbox() as client,
    ):
        url = service.url
        ids = register_all(run, client, env, test_accounts)
        if len(ids) != len(test_accounts):
            return 1
        token = user_token(client, ids, ["mail.read"])
        writer = user_token(client, ids, ["mail.read", "mail.write"])
        emails = {a["email"].lower() for a in test_accounts}
        print("\n== the MCP server over stdio, reading")
        anyio.run(check_tools, run, url, token, emails)
        inbox_only = user_token(client, ids, ["mail.read"], folders=["inbox"])
        print("\n== the MCP server over stdio, a grant narrowed to the inbox")
        anyio.run(check_folders, run, url, inbox_only, ids[0])
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
    return run.finish()


if __name__ == "__main__":
    sys.exit(main())
