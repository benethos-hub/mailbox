"""Sending through the MCP server of ``live/mcp_stdio.py``: mails from
the first test account to the second only, grants that narrow sending,
the audit, and the test mails deleted for good afterwards."""

from __future__ import annotations

import secrets
from typing import Any

from benethos_mailbox_client import SyncMailboxClient

from .admin import user_token
from .mail import delete_for_good, messages_with_subject
from .mcp_session import mcp_session, text_of
from .run import Run


def arrived(
    admin: SyncMailboxClient, account_id: str, subject: str
) -> list[dict[str, Any]]:
    """The messages with ``subject`` in the account, once one is there."""
    return messages_with_subject(admin, account_id, subject, tries=20)


async def check_sending(
    run: Run,
    url: str,
    token: str,
    admin: SyncMailboxClient,
    ids: list[str],
    to: str,
) -> None:
    """From the first test account to the second only: a mail sent twice
    with the same call arrives once, a draft is sent. Both are deleted for
    good afterwards, in the inbox and in the sent folder."""
    sender, receiver = ids
    subject = f"mailbox-service MCP send check {secrets.token_hex(4)}"
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
                not sent.is_error and bool((sent.structured_content or {}).get("sent")),
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
        body = admin.get_message(receiver, found[0]["id"]) if found else {}
        run.check(
            "the HTML mail arrived with both parts, the text made from the HTML",
            "<b" in (body.get("html_body") or "")
            and (body.get("text_body") or "").strip() == "Hello HTML",
        )
    finally:
        delete_test_mails(admin, ids, subjects)


def delete_test_mails(
    admin: SyncMailboxClient, ids: list[str], subjects: list[str]
) -> None:
    """The mails with these subjects, for good: in the second test account's
    inbox and the first one's sent folder."""
    sender, receiver = ids
    places = [(receiver, "inbox"), (sender, "sent")]
    removed = sum(delete_for_good(admin, places, title) for title in subjects)
    print(f"      cleanup: {removed} test mail(s) deleted for good")


async def check_constraints(
    run: Run,
    url: str,
    admin: SyncMailboxClient,
    ids: list[str],
    emails: list[str],
) -> None:
    """Grants that narrow sending, and the audit. Only between the test
    accounts: the recipient that must be refused is the second test account
    too, so a failing check still sends nowhere else."""
    sender, _ = ids
    own, other = emails
    subject = f"mailbox-service MCP limit check {secrets.token_hex(4)}"
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
            listed = text_of(await session.call_tool("list_accounts", {}))
            run.check(
                "list_accounts names the limits before a send",
                f"only to {other}, at most 1 a day, 1 left now" in listed,
            )
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
        audit = admin.request(
            "GET", f"/v1/accounts/{sender}/sends", params={"limit": 3}
        )
        outcomes = [record["outcome"] for record in audit.get("items", [])]
        run.check(
            "the audit names every attempt, newest first",
            outcomes == ["denied", "sent", "denied"],
            ", ".join(outcomes),
        )
    finally:
        delete_test_mails(admin, ids, subjects)
