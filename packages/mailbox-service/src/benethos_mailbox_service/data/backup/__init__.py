"""Encrypted backups of the whole database: ``backups`` writes, reads,
checks and restores them, ``blocks`` is the file of blocks and its
encryption."""

from __future__ import annotations

from .backups import (
    Manifest,
    create_backup,
    read_backup,
    restore_backup,
    restore_on_server,
    verify_backup,
    verify_in_memory,
    write_backup,
)
from .blocks import BLOCK, MAGIC, MAGIC_1, MAGIC_3, BackupError

__all__ = [
    "BLOCK",
    "MAGIC",
    "MAGIC_1",
    "MAGIC_3",
    "BackupError",
    "Manifest",
    "create_backup",
    "read_backup",
    "restore_backup",
    "restore_on_server",
    "verify_backup",
    "verify_in_memory",
    "write_backup",
]
