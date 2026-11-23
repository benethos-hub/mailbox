"""A lock file that tells a running program from a stopped one: one
writer per database or state file, across processes. The standard
library alone."""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class LockedError(Exception):
    """Another process holds the lock."""


@contextmanager
def exclusive_lock(path: Path) -> Iterator[None]:
    """Hold an exclusive lock on ``path`` while the block runs, across
    processes. Raises ``LockedError`` at once when another holds it. The
    operating system drops the lock when the process ends, even by a crash.
    The file is made for its owner alone (0600) where it is missing. An
    error of the folder or the file passes through as ``OSError``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            _lock(fd)
        except OSError:
            raise LockedError(f"{path} is locked by another process") from None
        try:
            yield
        finally:
            _unlock(fd)
    finally:
        os.close(fd)


if sys.platform == "win32":
    import msvcrt

    def _lock(fd: int) -> None:
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)

    def _unlock(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _lock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)
