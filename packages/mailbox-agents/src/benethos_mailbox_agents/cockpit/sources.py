"""Where the cockpit finds the state files: in the data folder and in
its direct folders, one folder per volume of an agent.

A page never takes a path from its address. It names an instance, and
the name is looked up among the files found here, so an unknown name or
one with ``..`` in it finds nothing.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

__all__ = ["StateFile", "find", "found", "stopped"]


@dataclass(frozen=True, slots=True)
class StateFile:
    """A state file and the name the cockpit shows it under: its name
    without the ending, with the folder before it when two folders hold a
    file of the same name."""

    name: str
    path: Path


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


def find(data_dir: Path, name: str) -> StateFile | None:
    """The state file shown as ``name``, None when there is none."""
    return next((file for file in found(data_dir) if file.name == name), None)


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
