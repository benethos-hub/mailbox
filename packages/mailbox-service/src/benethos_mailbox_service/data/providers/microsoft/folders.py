"""The folders of a Microsoft account: Exchange's own, and ``all``, which
Exchange has not (UNIFORM 6.5): every folder but the trash and junk."""

from __future__ import annotations

from ...models import Folder
from ...protocols import path_part
from . import mappers
from .api import PAGE_SIZE, Graph
from .shapes import Listing, MailFolder


async def list_folders(graph: Graph) -> list[Folder]:
    return [*await kept(graph), mappers.all_mail()]


async def kept(graph: Graph) -> list[Folder]:
    """The folders Exchange keeps, without ``all``."""
    roles = await graph.folder_roles()
    root = await graph.root_id()
    params = {"$select": mappers.FOLDER_FIELDS, "$top": str(PAGE_SIZE)}
    found: list[Folder] = []
    waiting = await graph.all(Listing[MailFolder], "/me/mailFolders", params)
    while waiting:
        item = waiting.pop(0)
        found.append(mappers.folder(item, roles, root))
        if item.child_folder_count:
            waiting.extend(
                await graph.all(
                    Listing[MailFolder],
                    f"/me/mailFolders/{path_part(item.id)}/childFolders",
                    params,
                )
            )
    return found


async def create_folder(graph: Graph, name: str, parent_id: str | None) -> Folder:
    path = (
        f"/me/mailFolders/{path_part(parent_id)}/childFolders"
        if parent_id
        else "/me/mailFolders"
    )
    item = await graph.read(MailFolder, "POST", path, json_body={"displayName": name})
    return mappers.folder(item, await graph.folder_roles(), await graph.root_id())


async def update_folder(
    graph: Graph, folder_id: str, name: str, parent_id: str | None
) -> Folder:
    path = f"/me/mailFolders/{path_part(folder_id)}"
    item = await graph.read(MailFolder, "PATCH", path, json_body={"displayName": name})
    # The top of the folder tree is the mailbox's root folder, which
    # Graph names as the parent of a top-level folder.
    root = await graph.root_id()
    if (item.parent_folder_id or root) != (parent_id or root):
        item = await graph.move(MailFolder, path, parent_id or root)
    return mappers.folder(item, await graph.folder_roles(), root)


async def delete_folder(graph: Graph, folder_id: str) -> None:
    await graph.call("DELETE", f"/me/mailFolders/{path_part(folder_id)}")
