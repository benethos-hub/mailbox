"""Mail too large for one Graph request. Graph takes at most 4 MB per
request, and a draft's MIME travels in base64. A larger mail is created
without its attachments, which follow one by one: a small file in one
request, a larger one through an upload session, in ranges. Microsoft
documents both ways ("Attach large files to Outlook messages")."""

from __future__ import annotations

import base64
from collections.abc import Awaitable, Callable
from typing import Any

from benethos_mailbox_common.values import sizes

from ....errors import MailboxServiceError
from ...mail import compose
from . import mappers
from .graph import Graph, id_
from .shapes import Message as GraphMessage
from .shapes import UploadSession

# A MIME sent in one request, well below 4 MB in base64.
ONE_REQUEST = 5 * sizes.MIB // 2
# From here a file goes through an upload session, below it in one
# request, as Microsoft documents: "3 MB". Counted in decimal, so a file
# just below still fits one request of 4 MB in base64 **(unverified)**.
SESSION = 3_000_000


async def create_draft(
    graph: Graph, raw: bytes, drop: Callable[[str], Awaitable[None]]
) -> GraphMessage:
    """A draft of ``raw``. Where it does not fit one request, its files
    follow one by one, and where one of them fails, ``drop`` takes the
    draft back."""
    if len(raw) <= ONE_REQUEST:
        return await _from_mime(graph, raw)
    rest, files = compose.without_attachments(raw)
    draft = await _from_mime(graph, rest)
    if not files:
        return draft
    try:
        for file in files:
            await _attach(graph, draft.id, file)
    except MailboxServiceError as exc:
        try:
            await drop(draft.id)
        except MailboxServiceError:
            raise exc.noting(
                f"the draft {draft.id} stays, without all its files"
            ) from None
        raise
    # Graph's answer to the draft knew no attachments yet.
    return await graph.read(
        GraphMessage,
        "GET",
        f"/me/messages/{id_(draft.id)}",
        params=mappers.SUMMARY_PARAMS,
    )


async def _from_mime(graph: Graph, raw: bytes) -> GraphMessage:
    return await graph.read(
        GraphMessage,
        "POST",
        "/me/messages",
        content=base64.b64encode(raw),
        content_type="text/plain",
    )


async def _attach(graph: Graph, draft_id: str, file: compose.Attached) -> None:
    path = f"/me/messages/{id_(draft_id)}/attachments"
    item: dict[str, Any] = {
        "name": file.filename or "attachment",
        "contentType": file.content_type,
        "isInline": file.inline,
    }
    if file.content_id:
        item["contentId"] = file.content_id.strip().strip("<>")
    if len(file.data) < SESSION:
        await graph.call(
            "POST",
            path,
            json_body={
                "@odata.type": "#microsoft.graph.fileAttachment",
                **item,
                "contentBytes": base64.b64encode(file.data).decode(),
            },
        )
        return
    session = await graph.read(
        UploadSession,
        "POST",
        f"{path}/createUploadSession",
        json_body={
            "AttachmentItem": {"attachmentType": "file", "size": len(file.data), **item}
        },
    )
    await graph.upload(session.upload_url, file.data)
