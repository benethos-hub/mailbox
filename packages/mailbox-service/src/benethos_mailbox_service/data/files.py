"""Files the data layer writes for its owner alone.

The database, a backup and a key file each hold secrets or their hashes.
They are created readable by their owner only (0600), never over an
existing file. Windows has no such modes, but there the exclusive
create still holds. A lock file tells a running service from a stopped
one.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


def create_private(path: Path, data: bytes = b"") -> None:
    """Create ``path`` with ``data``, for the owner alone. Fails when the
    file exists, so nothing is ever overwritten by accident."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as file:
        file.write(data)


class LockedError(Exception):
    """Another process holds the lock."""


@contextmanager
def exclusive_lock(path: Path) -> Iterator[None]:
    """Hold an exclusive lock on ``path`` while the block runs, across
    processes. Raises ``LockedError`` at once when another holds it. The
    operating system drops the lock when the process ends, even by a crash."""
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
