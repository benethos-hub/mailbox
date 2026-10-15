"""A folder's messages through Graph, newest first, and the search
results under their immutable ids."""

from __future__ import annotations

from urllib.parse import urlencode

from ...models import MessageFilter, MessageSummary, Page
from ...protocols import path_part
from .. import rules
from . import mappers
from .api import Graph, own_path
from .shapes import Batch, Listing
from .shapes import Message as GraphMessage


async def list_messages(
    graph: Graph,
    folder_id: str,
    limit: int,
    cursor: str | None,
    search: MessageFilter | None,
) -> Page[MessageSummary]:
    """The folder ``all`` is every folder but the trash and junk."""
    query, rest = mappers.query(search)
    # Graph's next page carries the query it was asked with: bound to
    # the folder and the search, so another list's cursor is refused.
    scope = rules.cursor_scope(folder_id, search)
    if cursor:
        path = own_path(rules.cursor_value("m_", cursor, scope))
        body = await graph.read(Listing[GraphMessage], "GET", path)
    else:
        path = (
            "/me/messages"
            if folder_id == mappers.ALL
            else f"/me/mailFolders/{path_part(folder_id)}/messages"
        )
        params = {**mappers.SUMMARY_PARAMS, "$top": str(limit), **query}
        body = await graph.read(Listing[GraphMessage], "GET", path, params=params)
    found = body.value
    if "$search" in query:
        found = await _immutable(graph, found)
    items = [mappers.summary(item) for item in found]
    if folder_id == mappers.ALL:
        # Graph lists every folder: the trash and junk leave after
        # each page, so a page can come back short.
        outside = await _outside_all(graph)
        items = [i for i in items if not outside.intersection(i.folder_ids)]
    link = body.next_link
    return Page[MessageSummary](
        items=[item for item in items if mappers.keeps(item, rest)],
        next_cursor=rules.bound_cursor("m_", scope, own_path(link)) if link else None,
    )


async def _outside_all(graph: Graph) -> set[str]:
    """The folders ``all`` leaves out: the trash and junk."""
    roles = await graph.folder_roles()
    return {f for f, role in roles.items() if role in mappers.OUTSIDE_ALL}


async def _immutable(graph: Graph, items: list[GraphMessage]) -> list[GraphMessage]:
    """Search results under their immutable ids.

    Seen live: Graph's search ignores the preference for immutable ids,
    a message fetched by such an id comes back under it again, and
    ``translateExchangeIds`` is refused for personal accounts. A list
    filtered by ``internetMessageId`` does answer with immutable ids:
    so each result is looked up by its Message-ID, twenty to a JSON
    batch, in the folder it was found in. One that cannot be looked
    up keeps the id the search gave.
    """
    ids: dict[str, str] = {}
    wanted = [item for item in items if item.internet_message_id]
    urls = []
    for item in wanted:
        header = (item.internet_message_id or "").replace("'", "''")
        query = urlencode(
            {
                "$select": "id,parentFolderId",
                "$filter": f"internetMessageId eq '{header}'",
            }
        )
        urls.append(f"/me/messages?{query}")
    found = await graph.batch(urls, Batch[Listing[GraphMessage]])
    for n, body in found.items():
        item = wanted[n]
        same = [f for f in body.value if f.parent_folder_id == item.parent_folder_id]
        if len(same) == 1:
            ids[item.id] = same[0].id
    return [item.model_copy(update={"id": ids.get(item.id, item.id)}) for item in items]
