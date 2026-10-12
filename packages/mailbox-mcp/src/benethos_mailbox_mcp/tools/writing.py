"""Writing tools: change mail, create, rename and move a folder."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

from .. import render
from ..errors import ToolError
from .base import changes, client

MAX_BATCH = 100

Folders = Annotated[
    list[str] | None,
    Field(
        max_length=20,
        description=(
            "Folder ids or roles. Only where a mail can be in several folders,"
            " such as Gmail's labels"
        ),
    ),
]

Keywords = Annotated[
    list[str] | None,
    Field(max_length=50, description="Keywords, such as $junk or a word of your own"),
]


async def update_messages(
    account_id: str,
    message_ids: Annotated[list[str], Field(min_length=1, max_length=MAX_BATCH)],
    unread: bool | None = None,
    starred: bool | None = None,
    move_to: Annotated[
        str | None,
        Field(description="Folder id, or a role such as archive, inbox, junk"),
    ] = None,
    add_folders: Folders = None,
    remove_folders: Folders = None,
    add_keywords: Keywords = None,
    remove_keywords: Keywords = None,
    trash: Annotated[
        bool, Field(description="Into the trash, alone and without other changes")
    ] = False,
) -> dict[str, Any]:
    """Change mail of one account: mark read or unread, star, move,
    archive, label, add and remove keywords, or put into the trash. At
    Gmail a label is a folder: add_folders labels a mail and leaves it
    where it is, remove_folders takes a label off, remove_folders inbox
    archives it. Ids stay the same after a move. Answers which ids were
    done and which failed, with the reason."""
    labels = (add_folders, remove_folders, add_keywords, remove_keywords)
    if trash:
        if (
            unread is not None
            or starred is not None
            or move_to is not None
            or any(labels)
        ):
            raise ToolError("trash goes alone, without other changes")
        outcome = await client().trash_messages(account_id, message_ids)
    else:
        if unread is None and starred is None and move_to is None and not any(labels):
            raise ToolError(
                "nothing to change: give unread, starred, move_to, add_folders, "
                "remove_folders, add_keywords, remove_keywords or trash"
            )
        if move_to is not None and (add_folders or remove_folders):
            raise ToolError("move_to sets the folder: not beside add or remove")
        outcome = await client().update_messages(
            account_id,
            message_ids,
            unread=unread,
            starred=starred,
            folder_id=move_to,
            add_folder_ids=add_folders or None,
            remove_folder_ids=remove_folders or None,
            add_keywords=add_keywords or None,
            remove_keywords=remove_keywords or None,
        )
    return render.outcome(outcome)


async def create_folder(
    account_id: str,
    name: str,
    parent: Annotated[
        str | None,
        Field(description="Folder id or role to create it in. Left out: the top"),
    ] = None,
) -> dict[str, Any]:
    """Create a folder in an account. Answers its id, which update_messages
    takes as move_to."""
    folder = await client().create_folder(account_id, name, parent)
    return {"id": folder.id, "name": folder.name}


async def update_folder(
    account_id: str,
    folder_id: str,
    name: Annotated[str | None, Field(description="The new name")] = None,
    parent: Annotated[
        str | None, Field(description="Folder id or role to move it into")
    ] = None,
    to_top: Annotated[bool, Field(description="Move it to the top")] = False,
) -> dict[str, Any]:
    """Rename a folder or move it, with the mail and folders inside. Answers
    its id from now on: on IMAP it follows the name and the place."""
    if parent is not None and to_top:
        raise ToolError("parent or to_top, not both")
    if name is None and parent is None and not to_top:
        raise ToolError("nothing to change: give name, parent or to_top")
    moved: dict[str, Any] = {"parent_id": None} if to_top else {}
    if parent is not None:
        moved["parent_id"] = parent
    folder = await client().update_folder(account_id, folder_id, name=name, **moved)
    return {"id": folder.id, "name": folder.name}


TOOLS = (
    # Setting a flag or a folder again changes nothing. A message in the
    # trash already is refused, not deleted.
    changes(
        update_messages,
        "Change messages",
        "write",
        "batch_messages",
        destructive=True,
        idempotent=True,
    ),
    changes(
        create_folder,
        "Create a folder",
        "write",
        "create_folder",
        destructive=False,
        idempotent=False,
    ),
    # A rename changes where other mail programs find the folder. The same
    # name and place again change nothing.
    changes(
        update_folder,
        "Rename or move a folder",
        "write",
        "update_folder",
        destructive=True,
        idempotent=True,
    ),
)
