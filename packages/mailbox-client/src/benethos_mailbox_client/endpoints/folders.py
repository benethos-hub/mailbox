"""The folders of an account: listed, made, renamed or moved, and
deleted, read into ``Folder``."""

from __future__ import annotations

from types import EllipsisType
from typing import Any

from ..calls import Call, given, nothing, path
from ..models import Folder


def list_folders(account_id: str) -> Call[list[Folder]]:
    return Call(
        "GET",
        path("accounts", account_id, "folders"),
        lambda found: [_folder(item) for item in found],
    )


def create_folder(account_id: str, name: str, parent_id: str | None) -> Call[Folder]:
    """A new folder. ``parent_id`` may be a role such as ``archive``."""
    return Call(
        "POST",
        path("accounts", account_id, "folders"),
        _folder,
        json=given({"name": name, "parent_id": parent_id}),
    )


def update_folder(
    account_id: str,
    folder_id: str,
    *,
    name: str | None = None,
    parent_id: str | None | EllipsisType = ...,
) -> Call[Folder]:
    """Rename a folder, or move it: ``parent_id`` a folder id or a role,
    None the top, left as ``...`` where it is. On IMAP the id follows the
    name and the place: the answer has the new one."""
    body = given({"name": name})
    if parent_id is not ...:
        body["parent_id"] = parent_id
    return Call(
        "PATCH", path("accounts", account_id, "folders", folder_id), _folder, json=body
    )


def delete_folder(account_id: str, folder_id: str) -> Call[None]:
    """Only an empty folder without folders inside goes."""
    return Call("DELETE", path("accounts", account_id, "folders", folder_id), nothing)


def _folder(item: dict[str, Any]) -> Folder:
    return Folder(
        id=str(item["id"]),
        name=str(item["name"]),
        role=item.get("role"),
        unread=item.get("unread"),
        total=item.get("total"),
    )
