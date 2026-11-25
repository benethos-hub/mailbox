"""Sending tools: a new mail, a draft, each at once or through the
outbox, and the outbox itself. A send cannot be taken back."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import Field

from benethos_mailbox_common.values import canonical, secret

from .. import answers, render
from .base import AccountId, Cursor, DraftId, Limit, changes, client, reads
from .compose import (
    Action,
    Addresses,
    AttachFrom,
    Attachments,
    ForwardAs,
    Html,
    OriginalId,
    Quote,
    ReplyTo,
    Subject,
    Text,
    composed,
)

UseOutbox = Annotated[
    bool,
    Field(
        description="Put it into the outbox instead of sending at once: the "
        "service keeps it as a draft and sends it in the background, trying "
        "again while the mail server is away, so it is not lost. The answer "
        "says it is queued, not sent"
    ),
]
SendAt = Annotated[
    datetime | None,
    Field(
        description="When to send it, ISO 8601 with a time zone, at most 30 "
        "days ahead. Puts it into the outbox"
    ),
]
JobId = Annotated[str, Field(description="A send of the outbox, by its job_id")]
OutboxState = Annotated[
    Literal["queued", "sending", "copying", "sent", "failed", "unknown", "cancelled"]
    | None,
    Field(description="Only the sends in this state"),
]


def _idempotency_key(tool: str, account_id: str, arguments: Any) -> str:
    """The same call gives the same key: the service answers a repeat within
    24 hours with the first result instead of sending twice. Written as the
    service writes the fingerprint of a request (``canonical``): keys
    sorted, no spaces, ASCII."""
    call = canonical.canonical([tool, account_id, arguments])
    return "mcp-" + secret.digest(call)


async def send_message(
    account_id: AccountId,
    to: Addresses = None,
    cc: Addresses = None,
    bcc: Addresses = None,
    subject: Subject = "",
    text: Text = "",
    html: Html = None,
    original_id: OriginalId = None,
    action: Action = "reply",
    quote: Quote = True,
    forward_as: ForwardAs = "inline",
    reply_to: ReplyTo = None,
    attachments: Attachments = None,
    attach_from: AttachFrom = None,
    outbox: UseOutbox = False,
    send_at: SendAt = None,
) -> answers.Sent:
    """Send a mail at once. It cannot be taken back. With original_id it
    answers or forwards that message, and a reply without recipients goes
    where the original asks answers to go, its Reply-To, else its sender.
    The same call repeated within 24 hours sends nothing and
    answers the first result. It answers the id of the copy in the sent
    folder where the account keeps one. refused lists recipients the
    server did not take. With outbox or send_at it is queued instead and
    goes out in the background: use it when the mail must not be lost to
    a mail server that is away, or to send it later. When a person should
    look at the mail first, use create_draft instead."""
    body = composed(
        to,
        cc,
        bcc,
        subject,
        text,
        html,
        original_id,
        action,
        reply_to=reply_to,
        quote=quote,
        forward_as=forward_as,
        attachments=attachments,
        attach_from=attach_from,
    )
    if outbox or send_at is not None:
        when = send_at.isoformat() if send_at else None
        key = _idempotency_key("queue_message", account_id, [body, when])
        queued = await client().queue_message(account_id, body, key, send_at)
        return render.queued(queued)
    key = _idempotency_key("send_message", account_id, body)
    return render.sent(await client().send_message(account_id, body, key))


async def send_draft(
    account_id: AccountId,
    draft_id: DraftId,
    outbox: UseOutbox = False,
    send_at: SendAt = None,
) -> answers.Sent:
    """Send a draft as it is stored. It cannot be taken back. Afterwards the
    draft is gone. It answers the id of the copy in the sent folder where
    the account keeps one. Use it once a draft from create_draft or
    update_draft is right. The same call repeated within 24 hours sends
    nothing and answers the first result. With outbox or send_at it is
    queued instead and goes out in the background. A draft changed before
    then is not sent."""
    if outbox or send_at is not None:
        when = send_at.isoformat() if send_at else None
        key = _idempotency_key("queue_draft", account_id, [draft_id, when])
        queued = await client().queue_draft(account_id, draft_id, key, send_at)
        return render.queued(queued)
    key = _idempotency_key("send_draft", account_id, draft_id)
    return render.sent(await client().send_draft(account_id, draft_id, key))


async def list_outbox(
    account_id: AccountId,
    state: OutboxState = None,
    limit: Limit = 20,
    cursor: Cursor = None,
) -> answers.Outbox:
    """The sends of the outbox of an account, newest first: those waiting
    and those that ended, with their state. It reads only. Use it to learn
    whether a queued send went out, or to find one for cancel_send."""
    return render.outbox(
        await client().list_outbox(account_id, state=state, limit=limit, cursor=cursor)
    )


async def cancel_send(account_id: AccountId, job_id: JobId) -> answers.OutboxJob:
    """Cancel a send of the outbox that still waits. Its draft stays in the
    drafts folder. One that is being sent or ended cannot be cancelled."""
    return render.outbox_job(await client().cancel_send(account_id, job_id))


TOOLS = (
    # A repeated send within 24 hours sends nothing (Idempotency-Key). It is
    # still marked as not idempotent: after that time it sends again.
    changes(
        send_message,
        "Send a mail",
        "send",
        "send_message",
        destructive=True,
        idempotent=False,
    ),
    changes(
        send_draft,
        "Send a draft",
        "send",
        "send_draft",
        destructive=True,
        idempotent=False,
    ),
    reads(list_outbox, "List the outbox", "list_outbox", kind="send"),
    # Cancelling twice ends as it began: the send does not go out.
    changes(
        cancel_send,
        "Cancel a queued send",
        "send",
        "cancel_send",
        destructive=False,
        idempotent=True,
    ),
)
