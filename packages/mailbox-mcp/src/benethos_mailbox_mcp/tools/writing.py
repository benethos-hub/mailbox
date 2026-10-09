"""Writing tools: change mail, create a folder."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

from .. import render
from ..errors import ToolError
from .base import changes, client

MAX_BATCH = 100


async def update_messages(
    account_id: str,
    message_ids: Annotated[list[str], Field(min_length=1, max_length=MAX_BATCH)],
    unread: bool | None = None,
    starred: bool | None = None,
    move_to: Annotated[
        str | None,
        Field(description="Folder id, or a role such as archive, inbox, junk"),
    ] = None,
    trash: Annotated[
        bool, Field(description="Into the trash, alone and without other changes")
    ] = False,
) -> dict[str, Any]:
    """Change mail of one account: mark read or unread, star, move to a
    folder or archive, or put into the trash. Ids stay the same after a
    move. Answers which ids were done and which failed, with the reason."""
    if trash:
        if unread is not None or starred is not None or move_to is not None:
            raise ToolError("trash goes alone, without other changes")
        outcome = await client().trash_messages(account_id, message_ids)
    else:
        if unread is None and starred is None and move_to is None:
            raise ToolError("nothing to change: give unread, starred, move_to or trash")
        outcome = await client().update_messages(
            account_id, message_ids, unread=unread, starred=starred, folder_id=move_to
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
)
