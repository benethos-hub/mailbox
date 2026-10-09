"""Folders as Gmail's labels. A label nests in another by its name,
``a/b`` in ``a``: a rename renames the labels inside too, so they stay
where they are. Gmail's own labels cannot be changed."""

from __future__ import annotations

from ....errors import BadRequestError, NotFoundError
from ...models import Folder
from . import mappers
from .api import GmailApi, id_
from .reading import at_once
from .shapes import Label


async def list_folders(api: GmailApi) -> list[Folder]:
    """The folders, each with its counts."""
    labels = [label for label in await api.labels() if mappers.is_folder(label)]
    return mappers.folders(await _counted(api, labels))


async def _counted(api: GmailApi, labels: list[Label]) -> list[Label]:
    """Each label read again, with its counts, in the same order. A label
    gone since stays as it was listed."""
    found = await at_once((label.id for label in labels), api.label)
    return [found.get(label.id, label) for label in labels]


async def create_folder(api: GmailApi, name: str, parent_id: str | None) -> Folder:
    parent = await _own(api, parent_id) if parent_id is not None else None
    label = await api.read(
        Label,
        "POST",
        "/labels",
        json_body={
            "name": mappers.label_name(_name(name), parent),
            "labelListVisibility": "labelShow",
            "messageListVisibility": "show",
        },
    )
    api.forget()
    return Folder(id=label.id, name=name, parent_id=parent.id if parent else None)


async def update_folder(
    api: GmailApi, folder_id: str, name: str, parent_id: str | None
) -> Folder:
    label = await _own(api, folder_id)
    parent = await _own(api, parent_id) if parent_id is not None else None
    if parent is not None and _inside(parent, label):
        raise BadRequestError("a label cannot move into itself")
    old = label.name or ""
    new = mappers.label_name(_name(name), parent)
    if new != old:
        inside = [x for x in await api.labels() if _inside(x, label)]
        await _rename(api, label.id, new)
        for child in inside:
            await _rename(api, child.id, new + (child.name or "")[len(old) :])
        api.forget()
    return Folder(id=label.id, name=name, parent_id=parent.id if parent else None)


async def delete_folder(api: GmailApi, folder_id: str) -> None:
    label = await _own(api, folder_id)
    await api.call("DELETE", f"/labels/{id_(label.id)}")
    api.forget()


async def _rename(api: GmailApi, label_id: str, name: str) -> None:
    await api.call("PATCH", f"/labels/{id_(label_id)}", json_body={"name": name})


def _inside(label: Label, outer: Label) -> bool:
    """Whether ``label`` is ``outer`` or nests in it."""
    name, top = label.name or "", outer.name or ""
    return bool(top) and (name == top or name.startswith(top + "/"))


def _name(name: str) -> str:
    if "/" in name:
        raise BadRequestError("a gmail label name holds no /: it nests labels")
    return name


async def _own(api: GmailApi, folder_id: str) -> Label:
    """A label a person made: Gmail's own cannot be changed or hold others."""
    for label in await api.labels():
        if label.id == folder_id:
            if label.type != "user":
                raise BadRequestError(f"gmail's own folder {folder_id} stays as it is")
            return label
    if folder_id == mappers.ALL_MAIL:
        raise BadRequestError("gmail's own folder All Mail stays as it is")
    raise NotFoundError(f"folder {folder_id} not found")
