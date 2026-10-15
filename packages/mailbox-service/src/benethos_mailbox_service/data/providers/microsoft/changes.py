"""What the sync asks of a Microsoft account. Ids are stable: the domain
keeps no id mapping for this provider, so the states and contents serve
checks such as "is the folder empty". What changed in a folder comes
from Graph's delta queries."""

from __future__ import annotations

from ....errors import ProviderError
from ...mail import ThreadHeaders
from ...protocols import path_part
from ..base import ChangedMessage, FolderChanges
from . import folders
from .api import PAGE_SIZE, Graph, own_path
from .shapes import Batch, Item, Listing
from .shapes import Message as GraphMessage


async def folder_states(graph: Graph) -> dict[str, str]:
    """Graph reports no UIDNEXT: the counts stand in. A message that
    arrives read while another leaves goes unnoticed until the next
    change, which the sync then catches up on."""
    return {f.id: f"{f.total}:{f.unread}" for f in await folders.kept(graph)}


async def folder_contents(graph: Graph, folder_id: str) -> list[str]:
    items = await graph.all(
        Listing[Item],
        f"/me/mailFolders/{path_part(folder_id)}/messages",
        {"$select": "id", "$top": str(PAGE_SIZE)},
    )
    return [item.id for item in items]


async def message_headers(
    graph: Graph, message_ids: list[str]
) -> dict[str, ThreadHeaders]:
    """Twenty to a JSON batch. A message that is gone is left out."""
    urls = [
        f"/me/messages/{path_part(message_id)}?$select=internetMessageId"
        for message_id in message_ids
    ]
    found = await graph.batch(urls, Batch[GraphMessage])
    return {
        message_ids[n]: ThreadHeaders(body.internet_message_id)
        for n, body in found.items()
    }


async def folder_changes(
    graph: Graph, folder_id: str, token: str | None
) -> FolderChanges:
    """A delta query of the folder's messages. The token is Graph's
    deltaLink, below ``/v1.0``. A message moved out of the folder comes
    as removed, one moved in as changed, under the same immutable id.
    Every message carries when it came."""
    if token is None:
        body = await graph.read(
            Listing[GraphMessage],
            "GET",
            f"/me/mailFolders/{path_part(folder_id)}/messages/delta",
            params={"$select": "id,createdDateTime"},
        )
    else:
        body = await graph.read(Listing[GraphMessage], "GET", own_path(token))
    changed: list[ChangedMessage] = []
    removed: list[str] = []
    delta = None
    async for page in graph.pages(body):
        for item in page.value:
            if item.removed is not None:
                removed.append(item.id)
            else:
                changed.append(ChangedMessage(item.id, item.created_date_time))
        delta = page.delta_link
    if not delta:
        raise ProviderError("microsoft answered a delta query without a link")
    return FolderChanges(own_path(delta), changed, removed)
