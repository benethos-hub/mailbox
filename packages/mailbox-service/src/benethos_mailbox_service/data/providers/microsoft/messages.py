"""One message of a Microsoft account, its conversation, and changes to
many: marks, keywords as Outlook's categories, moves, the trash and
deleting for good. A folder's list and the search are in ``listing``."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from ....errors import (
    BadRequestError,
    ConflictError,
    MailboxServiceError,
    NotFoundError,
    missing,
    missing_message,
)
from ...models import FolderRole, Message, MessageSummary, MessageUpdate
from ...protocols import path_part
from .. import rules
from ..base import ThreadMessages
from . import mappers
from .api import PAGE_SIZE, Graph, own_path
from .shapes import Item, Listing
from .shapes import Message as GraphMessage


@contextmanager
def _by_id(message_id: str) -> Iterator[None]:
    """A refusal of a request whose only input is the id, as the message
    missing. Graph answers 400 for an id it cannot read, where the other
    providers answer 404."""
    try:
        yield
    except BadRequestError:
        raise missing_message(message_id) from None


async def summary_of(graph: Graph, path: str) -> GraphMessage:
    return await graph.read(GraphMessage, "GET", path, params=mappers.SUMMARY_PARAMS)


async def get_message(graph: Graph, message_id: str) -> Message:
    """What Graph knows of the message, and what its MIME says: the
    bodies, the headers and the attachments as the mail has them, read
    as for any other provider. Graph's own fields would answer
    Exchange's HTML for a plain text mail, and no attachments for a mail
    with inline images only."""
    with _by_id(message_id):
        item = await summary_of(graph, f"/me/messages/{path_part(message_id)}")
    return mappers.message(item, await get_raw(graph, message_id))


async def folders_of(graph: Graph, message_ids: list[str]) -> dict[str, list[str]]:
    """The folder of each message that is there, nothing else of it."""
    found: dict[str, list[str]] = {}
    for message_id in message_ids:
        try:
            with _by_id(message_id):
                placed = await graph.placed(f"/me/messages/{path_part(message_id)}")
        except NotFoundError:
            continue
        parent = placed.parent_folder_id
        found[message_id] = [parent] if parent else []
    return found


async def get_raw(graph: Graph, message_id: str) -> bytes:
    path = f"/me/messages/{path_part(message_id)}/$value"
    with _by_id(message_id):
        return (await graph.call("GET", path)).body


async def thread_messages(graph: Graph, thread_id: str, limit: int) -> ThreadMessages:
    """A conversation's messages in every folder, filtered by its id,
    seen live. Graph refuses an order beside this filter, so they are
    sorted here. Of a longer conversation the pages read first are kept
    **(unverified)**."""
    conversation = thread_id.replace("'", "''")
    params = {
        **mappers.SUMMARY_PARAMS,
        "$filter": f"conversationId eq '{conversation}'",
        "$top": str(PAGE_SIZE),
    }
    body = await graph.read(Listing[GraphMessage], "GET", "/me/messages", params=params)
    found = list(body.value)
    link = body.next_link
    while link and len(found) <= limit:
        body = await graph.read(Listing[GraphMessage], "GET", own_path(link))
        found += body.value
        link = body.next_link
    if not found:
        raise missing("thread", thread_id)
    every = sorted(
        (mappers.summary(item) for item in found),
        key=lambda m: (m.received is None, m.received),
    )
    return ThreadMessages(every[-limit:], truncated=bool(link) or len(every) > limit)


async def update_messages(
    graph: Graph, message_ids: list[str], changes: MessageUpdate
) -> dict[str, MessageSummary | MailboxServiceError]:
    body = mappers.changes(changes.unread, changes.starred, changes.keywords)

    async def one(message_id: str) -> MessageSummary:
        # Judged per id, as the other adapters answer it.
        target = rules.move_target(changes, labels=False)
        if target == mappers.ALL:
            raise rules.into_all()
        path = f"/me/messages/{path_part(message_id)}"

        async def read() -> GraphMessage:
            with _by_id(message_id):
                return await summary_of(graph, path)

        item = None
        verb: dict[str, Any] = {}
        if mappers.touches_marks(changes):
            # Refused before anything changes.
            item = await read()
            verb = mappers.verb_after(item, changes)
        if changes.add_keywords or changes.remove_keywords:
            item = item or await read()
            categories = mappers.categories_after(item, changes)
            patch = {**body, **mappers.changes(None, None, categories), **verb}
        else:
            patch = {**body, **verb}
        if patch:
            await graph.call("PATCH", path, json_body=patch)
        if target is not None:
            await graph.move(GraphMessage, path, target)
        # Read again: Graph answers a change without the verb that says
        # whether the message is answered. Its id survives the move.
        return mappers.summary(await read())

    return await rules.per_id(message_ids, one)


async def delete_messages(
    graph: Graph, message_ids: list[str], permanent: bool
) -> dict[str, MessageSummary | None | MailboxServiceError]:
    try:
        trash = await graph.role_id(FolderRole.TRASH)
    except ConflictError as exc:
        return dict.fromkeys(message_ids, exc)

    async def one(message_id: str) -> MessageSummary | None:
        if permanent:
            await delete_for_good(graph, message_id, trash)
            return None
        path = f"/me/messages/{path_part(message_id)}"
        with _by_id(message_id):
            placed = await graph.placed(path)
        if placed.parent_folder_id == trash:
            raise rules.in_trash_already()
        return mappers.summary(await graph.move(GraphMessage, path, trash))

    return await rules.per_id(message_ids, one)


async def delete_for_good(
    graph: Graph, message_id: str, trash: str | None = None
) -> None:
    """Graph's DELETE outside the trash only moves the message there.
    For good means: into the trash, then deleted from it."""
    if trash is None:
        trash = await graph.role_id(FolderRole.TRASH)
    path = f"/me/messages/{path_part(message_id)}"
    moved = None
    with _by_id(message_id):
        placed = await graph.placed(path)
    if placed.parent_folder_id != trash:
        moved = await graph.move(Item, path, trash)
        path = f"/me/messages/{path_part(moved.id)}"
    try:
        await graph.call("DELETE", path)
    except MailboxServiceError as exc:
        if moved is None:
            raise
        raise exc.noting("the message is in the trash now") from None
