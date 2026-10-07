"""Folders made, renamed and deleted, each a sequence under the lock.

A step the guard runs again learns that it is a retry: finding its work
done then counts as done."""

from __future__ import annotations

from typing import Any

from ....errors import BadRequestError, ConflictError, NotSupportedError, missing
from ...models import Folder
from . import mappers
from .mailbox import Mailbox, names


def create_folder(
    box: Mailbox, name: str, parent_id: str | None, retried: bool = False
) -> Folder:
    raws = box.session.list_folders()
    full = full_name(box, raws, name, parent_id)
    if full in names(raws):
        if retried:
            return box.folder(full)  # the first try made it
        raise ConflictError(f"a folder {name} exists there already")
    box.session.create_folder(full)
    return box.folder(full)


def update_folder(
    box: Mailbox,
    folder_id: str,
    name: str,
    parent_id: str | None,
    retried: bool = False,
) -> Folder:
    raws = box.session.list_folders()
    old = mappers.folder_name(folder_id)
    if old not in names(raws):
        new = full_name(box, raws, name, parent_id)
        if retried and new in names(raws):
            return box.folder(new)  # the first try renamed it
        raise missing("folder", folder_id)
    new = full_name(box, raws, name, parent_id)
    if new == old:
        return box.folder(old)
    if new in names(raws):
        raise ConflictError(f"a folder {name} exists there already")
    if new.startswith(old + (delimiter(box, raws) or "\0")):
        raise BadRequestError("a folder cannot move into itself")
    box.session.rename_folder(old, new)
    return box.folder(new)


def delete_folder(box: Mailbox, folder_id: str, retried: bool = False) -> None:
    name = mappers.folder_name(folder_id)
    if name not in names(box.session.list_folders()):
        if retried:
            return  # the first try deleted it
        raise missing("folder", folder_id)
    box.session.delete_folder(name)


def full_name(box: Mailbox, raws: list[Any], name: str, parent_id: str | None) -> str:
    """The server's name for ``name`` below ``parent_id``, or at the top
    of the user's personal namespace."""
    found = delimiter(box, raws)
    if found and found in name:
        raise BadRequestError(f"a folder name cannot contain {found!r}: use parent_id")
    if parent_id is None:
        prefix, _ = box.session.personal_namespace()
        return prefix + name
    parent = mappers.folder_name(parent_id)
    if parent not in names(raws):
        raise missing("folder", parent_id)
    if not found:
        raise NotSupportedError("the mail server has no folder hierarchy")
    return parent + found + name


def delimiter(box: Mailbox, raws: list[Any]) -> str | None:
    found = next((raw.delimiter for raw in raws if raw.delimiter), None)
    return found or box.session.personal_namespace()[1]
