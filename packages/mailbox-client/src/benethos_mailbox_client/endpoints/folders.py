"""The folders of an account: listed, and a new one, read into
``Folder``."""

from __future__ import annotations

from typing import Any

from ..calls import Call, given, path
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


def _folder(item: dict[str, Any]) -> Folder:
    return Folder(
        id=str(item["id"]),
        name=str(item["name"]),
        role=item.get("role"),
        unread=item.get("unread"),
        total=item.get("total"),
    )
