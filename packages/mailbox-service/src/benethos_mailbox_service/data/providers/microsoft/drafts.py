"""Drafts of a Microsoft account, and sending, which sends a draft.

A draft is created from MIME and replaced by creating a new one, since
Graph cannot change a draft's MIME in place. One too large for one
request gets its files one by one (``uploads``)."""

from __future__ import annotations

from functools import partial

from ....errors import BadRequestError, MailboxServiceError, missing
from ...mail import compose
from ...models import FolderRole, MessageSummary, Page, SentMessage
from ...protocols import path_part
from .. import rules
from . import listing, mappers, messages, uploads
from .api import Graph


async def send(graph: Graph, raw: bytes, recipients: list[str]) -> SentMessage:
    """The way Microsoft documents to learn the sent copy: the MIME is
    saved as a draft, which is sent. The copy in Sent Items keeps the
    draft's immutable id. Graph takes the recipients from the MIME
    headers. Recipients the headers do not name are the Bcc ones: they
    go in a Bcc header, which Exchange takes out before delivery
    **(unverified)**. A draft that cannot be sent is deleted again."""
    for_good = partial(messages.delete_for_good, graph)
    draft = await uploads.create_draft(
        graph, compose.with_bcc(raw, recipients), for_good
    )
    try:
        await graph.call("POST", f"/me/messages/{path_part(draft.id)}/send")
    except MailboxServiceError as exc:
        try:
            await for_good(draft.id)
        except MailboxServiceError:
            raise exc.noting(f"it stays as the draft {draft.id}") from None
        raise
    roles = await graph.folder_roles()
    sent = next((k for k, v in roles.items() if v is FolderRole.SENT), None)
    return SentMessage(sent_copy=mappers.sent_copy(draft, sent))


async def list_drafts(
    graph: Graph, limit: int, cursor: str | None
) -> Page[MessageSummary]:
    drafts = await graph.role_id(FolderRole.DRAFTS)
    return await listing.list_messages(graph, drafts, limit, cursor, None)


async def save_draft(graph: Graph, raw: bytes, replaces: str | None) -> MessageSummary:
    for_good = partial(messages.delete_for_good, graph)
    if replaces is not None:
        await _draft(graph, replaces)
    item = await uploads.create_draft(graph, raw, for_good)
    if replaces is not None:
        await rules.replaced(
            item.id, lambda: for_good(replaces), lambda: for_good(item.id)
        )
    return mappers.summary(item)


async def get_draft(graph: Graph, draft_id: str) -> bytes:
    await _draft(graph, draft_id)
    return await messages.get_raw(graph, draft_id)


async def delete_draft(graph: Graph, draft_id: str) -> None:
    await _draft(graph, draft_id)
    await messages.delete_for_good(graph, draft_id)


async def _draft(graph: Graph, draft_id: str) -> None:
    """Only drafts: any other id is not found, so the draft operations
    reach no other mail."""
    try:
        draft = (await graph.placed(f"/me/messages/{path_part(draft_id)}")).is_draft
    except BadRequestError:
        draft = False
    if not draft:
        raise missing("draft", draft_id)
