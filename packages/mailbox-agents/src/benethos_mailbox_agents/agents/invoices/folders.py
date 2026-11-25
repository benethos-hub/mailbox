"""Where ``invoices`` looks for invoices, and where it puts one.

The folders it looks in are a setting, read at its start, so it works with
``categorization`` and without it (decided 2026-11-18): it knows nothing of
groups. ``MAILBOX_AGENTS_INVOICES_FOLDERS`` names them, separated by
commas, each written in one of three ways:

- a path, ``Providers/CloudHost``: that folder,
- ``Parent/*``: every folder directly below ``Parent``,
- ``*``: every folder at the top that has no role, the owner's own included
  (decided 2026-11-18). The inbox, sent mail, drafts, the trash, junk, the
  archive and the like have a role.

The inbox is always looked in. A message in the subfolder of a folder
looked in, or in a folder between the two, is not looked at, so an
invoice is not asked about twice. Another folder below one looked in is
looked in when the settings take it in, as ``Providers,Providers/*``
takes in ``Providers/CloudHost``. The subfolder is not looked in even
where the settings would take it in, as ``Invoices`` and ``Invoices/*``
take in ``Invoices/Rechnungen``. ``Parent/*`` and ``*`` are matched
against the path of the folder a message lies in, so a folder made after
the start, by ``categorization`` say, is looked in too.

``MAILBOX_AGENTS_INVOICES_SUBFOLDER`` is where an invoice goes, as
``{folder}/Rechnungen``: below the folder the message lies in.
``MAILBOX_AGENTS_INVOICES_INBOX_FOLDER`` is where an invoice found in the
inbox goes. Unset, it is marked and stays. The inbox folder is an end
station (decided 2026-11-19): looked in when the settings take it in, as
``*`` takes in one at the top, and an invoice there is marked and stays,
nothing is made below it. See docs/mailbox-agents/concept/agent-invoices.md.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from ...errors import ConfigError
from ...records import DISCARD_ROLES, FolderRef
from ...settings import PREFIX

__all__ = ["ALL_AT_TOP", "FOLDER", "Places"]

# Every folder at the top without a role.
ALL_AT_TOP = "*"

# What the subfolder's pattern starts with: the folder a message lies in.
FOLDER = "{folder}"


def _path(value: str, setting: str) -> str:
    """``value`` as a path of names between ``/``, or a ConfigError."""
    parts = value.split("/")
    if any(
        not p.strip()
        or p in (".", "..")
        or p != p.strip()
        or any(c in p for c in "*{}")
        for p in parts
    ):
        raise ConfigError(
            f"{PREFIX}{setting}: {value!r} is no folder, names between / are "
            "neither empty, . nor .., and hold no *, { or }"
        )
    return value


@dataclass(frozen=True)
class Places:
    """The folders ``invoices`` looks in, and where an invoice goes."""

    named: tuple[str, ...] = ()
    parents: tuple[str, ...] = ()
    top: bool = False
    subfolder: tuple[str, ...] = ()
    inbox_folder: str | None = None

    @classmethod
    def read(
        cls,
        folders: list[str],
        subfolder: str | None,
        inbox_folder: str | None,
    ) -> Places:
        """The places as the settings name them, or a ConfigError that says
        what is wrong."""
        named: list[str] = []
        parents: list[str] = []
        top = False
        for entry in (f.strip() for f in folders):
            if entry == ALL_AT_TOP:
                top = True
            elif entry.endswith("/" + ALL_AT_TOP):
                parents.append(_path(entry[: -len(ALL_AT_TOP) - 1], "INVOICES_FOLDERS"))
            else:
                named.append(_path(entry, "INVOICES_FOLDERS"))
        below: tuple[str, ...] = ()
        if subfolder:
            if not subfolder.startswith(FOLDER + "/"):
                raise ConfigError(
                    f"{PREFIX}INVOICES_SUBFOLDER: {subfolder!r} does not start with "
                    f"{FOLDER}/, the folder the message lies in"
                )
            rest = _path(subfolder[len(FOLDER) + 1 :], "INVOICES_SUBFOLDER")
            below = tuple(rest.split("/"))
        inbox = _path(inbox_folder, "INVOICES_INBOX_FOLDER") if inbox_folder else None
        return cls(
            named=tuple(dict.fromkeys(named)),
            parents=tuple(dict.fromkeys(parents)),
            top=top,
            subfolder=below,
            inbox_folder=inbox,
        )

    # -- where it looks -------------------------------------------------------------

    def _by_path(self, path: str, role: str | None) -> bool:
        """Whether the folder at ``path`` is one it looks in, the inbox
        aside. Never the subfolder of a folder it looks in or a folder
        between the two, whatever the settings match: an invoice put
        there is not filed again. The inbox folder is looked in when the
        settings take it in, as an end station."""
        if self._below_one(path):
            return False
        return self._matches(path, role)

    def is_end(self, folder: FolderRef) -> bool:
        """Whether ``folder`` is the inbox folder: an invoice there stays."""
        return folder.role != "inbox" and folder.path == self.inbox_folder

    def _matches(self, path: str, role: str | None) -> bool:
        """Whether the settings take in the folder at ``path``."""
        # A named folder of these roles is never looked in: a message there
        # is not the owner's to file, and the runtime refuses to touch it.
        if role in DISCARD_ROLES:
            return False
        if path in self.named:
            return True
        if role is not None:
            return False
        parent = path.rpartition("/")[0]
        if parent:
            return parent in self.parents
        return self.top

    def _prefixes(self) -> list[str]:
        """The parts of the subfolder pattern below ``{folder}``, from the
        first alone down to all of them: ``Rechnungen``, then
        ``Rechnungen/Eingang``."""
        return [
            "/".join(self.subfolder[:count])
            for count in range(1, len(self.subfolder) + 1)
        ]

    def _bases(self, path: str) -> list[str]:
        """The folders ``path`` would lie below as their subfolder, or as a
        folder between the two: for each prefix ``path`` ends in, the path
        before it."""
        return [
            path[: -len(prefix) - 1]
            for prefix in self._prefixes()
            if path.endswith("/" + prefix)
        ]

    def _below_one(self, path: str) -> bool:
        """Whether ``path`` is the subfolder of a folder the settings take
        in, or a folder between the two. The folder above is judged by
        its path alone, its role unknown here."""
        return any(self._matches(base, None) for base in self._bases(path))

    def looks_in(self, folder: FolderRef) -> bool:
        """Whether a message in ``folder`` is one to ask about."""
        return folder.role == "inbox" or self._by_path(folder.path, folder.role)

    # -- where an invoice goes ------------------------------------------------------

    def target(self, folder: FolderRef) -> str | None:
        """Where an invoice in ``folder`` goes: the subfolder below it, the
        inbox folder for the inbox. None when it stays, as in the inbox
        folder, and in the inbox when the inbox folder is set to the inbox
        itself."""
        if folder.role == "inbox":
            return None if self.inbox_folder == folder.path else self.inbox_folder
        if not self.subfolder or self.is_end(folder):
            return None
        return "/".join((folder.path, *self.subfolder))

    def steps(self, folder: FolderRef) -> tuple[str, ...]:
        """The folders from the one below ``folder`` down to its subfolder,
        the top first: those made when missing. None below the inbox
        folder."""
        if self.is_end(folder):
            return ()
        return tuple(f"{folder.path}/{prefix}" for prefix in self._prefixes())

    def may_create(self, path: str, folders: Mapping[str, FolderRef]) -> bool:
        """Whether ``path`` is the subfolder of a folder it looks in, or a
        folder between the two: what the runtime may make for it.
        ``folders`` are the account's folders by path: the folder it looks
        in must be one of them, and is judged with its role, so ``*``
        makes nothing below sent mail or drafts. The inbox folder is not
        made, nor anything below it, also where its path is the subfolder
        of a folder it looks in."""
        if path == self.inbox_folder:
            return False
        for name in self._bases(path):
            base = folders.get(name)
            if (
                base is not None
                and not self.is_end(base)
                and self._by_path(base.path, base.role)
            ):
                return True
        return False

    def describe(self, folders: Mapping[str, FolderRef]) -> list[str]:
        """A line for each folder of ``folders``, by path, that matters:
        the inbox, each folder it looks in with where an invoice there
        goes, the inbox folder, and each subfolder there is, which it does
        not look in. Sorted by path."""
        lines = []
        for path, found in sorted(folders.items()):
            if found.role == "inbox" and path == self.inbox_folder:
                lines.append(
                    f"{path}: looked in, the inbox folder is the inbox itself, "
                    "an invoice is marked and stays"
                )
            elif found.role == "inbox":
                lines.append(f"{path}: looked in, an invoice {self._goes(found)}")
            elif self.is_end(found):
                looked = self._by_path(path, found.role)
                lines.append(
                    f"{path}: end station, looked in, an invoice is marked and stays"
                    if looked
                    else f"{path}: inbox folder, not looked in"
                )
            elif self._by_path(path, found.role):
                lines.append(f"{path}: looked in, an invoice {self._goes(found)}")
            elif self.may_create(path, folders):
                lines.append(f"{path}: subfolder, not looked in")
        return lines

    def _goes(self, folder: FolderRef) -> str:
        target = self.target(folder)
        return f"moves to {target}" if target else "is marked and stays"

    def needed(self) -> tuple[str, ...]:
        """The folders that should be there: those named, the parents of
        ``Parent/*``, and the inbox folder."""
        found = (*self.named, *self.parents)
        if self.inbox_folder:
            found = (*found, self.inbox_folder)
        return tuple(dict.fromkeys(found))
