"""Writing through the MCP server of ``live/mcp_stdio.py``: a folder made,
renamed and removed in the first test account, a keyword added and taken
off, its newest inbox message starred, moved and trashed, then all put
back as it was."""

from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable
from typing import Any

from mcp import ClientSession

from benethos_mailbox_client import ApiError, MessageSummary, SyncMailboxClient

from .mcp_session import READ_TOOLS, mcp_session, text_of
from .run import Run

WRITE_TOOLS = READ_TOOLS | {"update_messages", "create_folder", "update_folder"}
# A keyword of this check alone, set and taken off again.
KEYWORD = "mcp-live"


async def rename_folder(
    run: Run, session: ClientSession, account_id: str, folder_id: str
) -> str:
    """The folder renamed through the tool. Its id from now on."""
    renamed = await session.call_tool(
        "update_folder",
        {
            "account_id": account_id,
            "folder_id": folder_id,
            "name": f"mcp-live-{secrets.token_hex(4)}",
        },
    )
    new_id = (renamed.structured_content or {}).get("id")
    run.check(
        "update_folder renames it, the id follows the name",
        not renamed.is_error and bool(new_id) and new_id != folder_id,
        text_of(renamed) if renamed.is_error else "",
    )
    return str(new_id or folder_id)


async def check_keywords(
    run: Run,
    update: Callable[..., Awaitable[dict[str, Any]]],
    admin: SyncMailboxClient,
    account_id: str,
    message: MessageSummary,
) -> None:
    """A keyword added and taken off, the others kept. A label refused,
    since an IMAP message is in one folder."""
    tagged = await update(add_keywords=[KEYWORD])
    now = admin.get_message(account_id, message.id)
    run.check(
        "update_messages adds a keyword and keeps the others",
        tagged.get("done") == [message.id]
        and set(now.keywords) == {*message.keywords, KEYWORD},
        str(tagged.get("error", "")),
    )
    untagged = await update(remove_keywords=[KEYWORD])
    now = admin.get_message(account_id, message.id)
    run.check(
        "update_messages takes it off again",
        untagged.get("done") == [message.id]
        and set(now.keywords) == set(message.keywords),
        str(untagged.get("error", "")),
    )
    labelled = await update(add_folders=["inbox"])
    run.check(
        "a label is refused where a message is in one folder",
        "exactly one folder" in str(labelled),
    )


async def check_writing(
    run: Run, url: str, token: str, admin: SyncMailboxClient, account_id: str
) -> None:
    """Folder, keywords, star, move and trash through the tools, then all
    put back."""
    inbox = next(f for f in admin.list_folders(account_id) if f.role == "inbox")
    newest = admin.list_messages(account_id, folder=inbox.id, limit=1).items
    if not newest:
        print("SKIP  no message in the inbox of the first test account")
        return
    message = newest[0]
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
                        "message_ids": [message.id],
                        **changes,
                    },
                )
                found: dict[str, Any] = result.structured_content or {}
                if result.is_error:
                    found = {"error": text_of(result)}
                return found

            start = await session.call_tool("whats_new", {"account_id": account_id})
            since = (start.structured_content or {}).get("state")
            run.check("whats_new hands out a state", not start.is_error and bool(since))

            created = await session.call_tool(
                "create_folder",
                {"account_id": account_id, "name": f"mcp-live-{secrets.token_hex(4)}"},
            )
            folder_id = (created.structured_content or {}).get("id")
            run.check("create_folder", not created.is_error and bool(folder_id))
            if folder_id:
                folder_id = await rename_folder(run, session, account_id, folder_id)
            await check_keywords(run, update, admin, account_id, message)

            starred = await update(starred=not message.starred)
            now = admin.get_message(account_id, message.id)
            run.check(
                "update_messages stars",
                starred.get("done") == [message.id]
                and now.starred is not message.starred,
                str(starred.get("error", "")),
            )
            await update(starred=message.starred)

            if folder_id:
                moved = await update(move_to=folder_id)
                now = admin.get_message(account_id, message.id)
                run.check(
                    "update_messages moves into the new folder, the id stays",
                    moved.get("done") == [message.id] and now.folder_ids == [folder_id],
                    str(moved.get("error", "")),
                )

            trashed = await update(trash=True)
            now = admin.get_message(account_id, message.id)
            trash = next(
                (f.id for f in admin.list_folders(account_id) if f.role == "trash"),
                None,
            )
            run.check(
                "update_messages trashes",
                trashed.get("done") == [message.id] and now.folder_ids == [trash],
                str(trashed.get("error", "")),
            )

            back = await update(move_to="inbox")
            now = admin.get_message(account_id, message.id)
            run.check(
                "update_messages moves back by role",
                back.get("done") == [message.id] and now.folder_ids == [inbox.id],
                str(back.get("error", "")),
            )

            news = await session.call_tool(
                "whats_new", {"account_id": account_id, "since": since}
            )
            changes = (news.structured_content or {}).get("changes", [])
            run.check(
                "whats_new names the message as updated",
                not news.is_error
                and any(
                    c["id"] == message.id and c["type"] == "message.updated"
                    for c in changes
                ),
                f"{len(changes)} changes",
            )
    finally:
        put_back(run, admin, account_id, message, inbox.id, folder_id)


def put_back(
    run: Run,
    admin: SyncMailboxClient,
    account_id: str,
    message: MessageSummary,
    inbox_id: str,
    folder_id: str | None,
) -> None:
    """Whatever failed: the message back in the inbox as it was, the test
    folder gone."""
    admin.request(
        "PATCH",
        f"/v1/accounts/{account_id}/messages/{message.id}",
        json={
            "folder_ids": [inbox_id],
            "starred": message.starred,
            "unread": message.unread,
        },
    )
    if KEYWORD not in message.keywords:
        admin.update_message(account_id, message.id, remove_keywords=[KEYWORD])
    if folder_id:
        try:
            admin.request("DELETE", f"/v1/accounts/{account_id}/folders/{folder_id}")
            removed = ""
        except ApiError as exc:
            removed = str(exc)
        run.check("the test folder removed again", not removed, removed)
