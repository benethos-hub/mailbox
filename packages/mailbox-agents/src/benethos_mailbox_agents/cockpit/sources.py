"""Where the cockpit finds the instances it shows, behind one seam: a
source names its instances, and each opens its state for reading and
says whether its writer stopped. The pages do not know which source an
instance comes from.

The first source is the state files: in the data folder and in its
direct folders, one folder per volume of an agent.

A page never takes a path or an address from its own address. It names
an instance, and the name is looked up among those the sources found,
so an unknown name or one with ``..`` in it finds nothing.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..store import Store

__all__ = [
    "Files",
    "Instance",
    "Source",
    "StateFile",
    "every",
    "find",
    "found",
    "stopped",
]


class Instance(Protocol):
    """An instance of an agent as the cockpit shows it."""

    @property
    def name(self) -> str:
        """The name the cockpit shows it under and finds it by."""
        ...

    def open(self) -> Store:
        """Its state, for reading beside the running agent."""
        ...

    def stopped(self) -> bool:
        """Whether its writer is known to have stopped."""
        ...


class Source(Protocol):
    """Where instances are found."""

    def found(self) -> Sequence[Instance]:
        """Every instance found now, by name. One that cannot be read is
        found all the same: its page says why."""
        ...


@dataclass(frozen=True, slots=True)
class StateFile:
    """A state file and the name the cockpit shows it under: its name
    without the ending, with the folder before it when two folders hold a
    file of the same name."""

    name: str
    path: Path

    def open(self) -> Store:
        return Store.open(self.path, read_only=True)

    def stopped(self) -> bool:
        return stopped(self.path)


@dataclass(frozen=True, slots=True)
class Files:
    """The state files in ``data_dir`` and its direct folders."""

    data_dir: Path

    def found(self) -> Sequence[Instance]:
        return found(self.data_dir)


def every(sources: Sequence[Source]) -> list[Instance]:
    """The instances of every source, by name. A name a source before
    took already is not shown twice: the later one is left out, so a
    page never opens another instance than the one its name showed."""
    taken: dict[str, Instance] = {}
    for source in sources:
        for instance in source.found():
            taken.setdefault(instance.name, instance)
    return sorted(taken.values(), key=lambda instance: instance.name)


def find(sources: Sequence[Source], name: str) -> Instance | None:
    """The instance shown as ``name``, None when there is none."""
    return next((found for found in every(sources) if found.name == name), None)


def _files(data_dir: Path) -> Iterator[Path]:
    if not data_dir.is_dir():
        return
    yield from sorted(path for path in data_dir.glob("*.db") if path.is_file())
    for folder in sorted(path for path in data_dir.iterdir() if path.is_dir()):
        yield from sorted(path for path in folder.glob("*.db") if path.is_file())


def found(data_dir: Path) -> list[StateFile]:
    """Every state file in ``data_dir`` and its direct folders, by name.
    A folder that cannot be read, or holds no file, adds none."""
    files: list[StateFile] = []
    names: set[str] = set()
    try:
        paths = list(_files(data_dir))
    except OSError:
        return []
    for path in paths:
        name = path.stem
        if name in names:
            name = f"{path.parent.name}-{path.stem}"
        names.add(name)
        files.append(StateFile(name, path))
    return sorted(files, key=lambda file: file.name)


def stopped(path: Path) -> bool:
    """Whether no writer holds the file open. A writer in WAL mode keeps
    ``-wal`` beside it with what it wrote, at the least the profile it
    writes when it starts, and takes it away when it closes the file
    cleanly. A reader in a folder it may write leaves an empty one behind,
    which says nothing of a writer. A writer that was killed leaves its
    ``-wal``, and so does one that stopped while a reader held the file:
    such a file reads as running, and as silent once the window of its
    health has passed."""
    wal = path.with_name(path.name + "-wal")
    try:
        return not wal.exists() or wal.stat().st_size == 0
    except OSError:
        return False
