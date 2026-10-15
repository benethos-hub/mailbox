"""The folders of the in-memory mailbox."""

from __future__ import annotations

from ....errors import ConflictError
from ...models import Folder
from .store import Store, folder


def create_folder(store: Store, name: str, parent_id: str | None) -> Folder:
    if parent_id is not None:
        folder(store, parent_id)
    if any(f.name == name and f.parent_id == parent_id for f in store.folders):
        raise ConflictError(f"a folder {name} exists there already")
    made = Folder(id=f"folder_{len(store.folders)}", name=name, parent_id=parent_id)
    store.folders.append(made)
    return made


def update_folder(
    store: Store, folder_id: str, name: str, parent_id: str | None
) -> Folder:
    found = folder(store, folder_id)
    if parent_id is not None:
        folder(store, parent_id)
    updated = found.model_copy(update={"name": name, "parent_id": parent_id})
    store.folders[store.folders.index(found)] = updated
    return updated


def delete_folder(store: Store, folder_id: str) -> None:
    store.folders.remove(folder(store, folder_id))
