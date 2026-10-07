"""The mailbox as one step sees it: the session, and the folders it lists
once. Every sequence of the adapter (``messages``, ``folders``,
``drafts``, ``sync``) works on one."""

from __future__ import annotations

from typing import Any

from ....errors import missing
from ...models import Folder, FolderRole
from ...protocols import ImapSession
from .. import rules
from ..base import Capability
from . import mappers


class Mailbox:
    def __init__(self, session: ImapSession, capabilities: frozenset[Capability]):
        self.session = session
        self.capabilities = capabilities
        self._folders: list[Folder] | None = None

    def fresh(self) -> None:
        """A new step: what the last one listed may have changed."""
        self._folders = None

    def list_folders(self, subscriptions: bool = False) -> list[Folder]:
        raws = self.session.folders.list_folders(subscriptions)
        prefix, _ = self.session.folders.personal_namespace()
        return mappers.folders(raws, prefix)

    def listed(self) -> list[Folder]:
        """The folders, listed once per step: a draft save asks for the
        drafts folder several times."""
        if self._folders is None:
            self._folders = self.list_folders()
        return self._folders

    def role_folder(self, role: FolderRole) -> str | None:
        """The server's name of the folder with ``role``, if there is one."""
        folder = rules.role_folder(self.listed(), role)
        return mappers.folder_name(folder.id) if folder is not None else None

    def required_folder(self, role: FolderRole) -> str:
        """The server's name of the folder with ``role``. ``no_folder``
        when the account has none."""
        return mappers.folder_name(rules.require_role_folder(self.listed(), role).id)

    def folder(self, name: str) -> Folder:
        """A folder as listed, with its role and subscription."""
        for folder in self.list_folders(subscriptions=True):
            if folder.id == mappers.folder_id(name):
                return folder
        raise missing("folder", name)


def names(raws: list[Any]) -> set[str]:
    """The server's names of listed folders."""
    return {raw.name for raw in raws}
