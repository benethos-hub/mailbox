"""Files the data layer writes for its owner alone.

The database, a backup and a key file each hold secrets or their hashes.
They are created readable by their owner only (0600), never over an
existing file. Windows has no such modes, but there the exclusive
create still holds.
"""

from __future__ import annotations

import os
from pathlib import Path


def create_private(path: Path, data: bytes = b"") -> None:
    """Create ``path`` with ``data``, for the owner alone. Fails when the
    file exists, so nothing is ever overwritten by accident."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as file:
        file.write(data)
