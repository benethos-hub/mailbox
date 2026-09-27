"""Encrypted backups of the whole database (CONCEPT 7.8).

File layout: a magic line, a JSON manifest line, then nonce and ciphertext.
The whole database is encrypted with a key derived from the master key, and
the magic and manifest are authenticated with it, so neither can be altered
unnoticed. The master key itself is never in a backup.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from ..files import LockedError, create_private, exclusive_lock
from ..storage import Database, inspect_snapshot
from ..storage.sqlite import SCHEMA_VERSION, service_lock
from . import cipher

MAGIC = b"MAILBOX-SERVICE-BACKUP 1\n"
_KEY_INFO = b"mailbox-service backup v1"


class BackupError(Exception):
    """A backup that cannot be read, decrypted or restored."""


@dataclass(frozen=True)
class Manifest:
    service_version: str
    schema_version: int
    created_at: str
    sha256: str


def create_backup(
    db: Database, master_key: bytes, target: Path, service_version: str
) -> Manifest:
    if target.exists():
        raise BackupError(f"{target} exists, refusing to overwrite it")
    data = db.snapshot()
    try:
        schema_version = inspect_snapshot(data)
    except ValueError as exc:
        raise BackupError(f"the database cannot be backed up: {exc}") from None
    manifest = Manifest(
        service_version=service_version,
        schema_version=schema_version,
        created_at=datetime.now(UTC).isoformat(),
        sha256=hashlib.sha256(data).hexdigest(),
    )
    write_backup(data, manifest, master_key, target)
    return manifest


def write_backup(
    data: bytes, manifest: Manifest, master_key: bytes, target: Path
) -> None:
    header = MAGIC + json.dumps(asdict(manifest)).encode() + b"\n"
    nonce, ciphertext = cipher.encrypt(_backup_key(master_key), data, header)
    try:
        create_private(target, header + nonce + ciphertext)
    except OSError as exc:
        raise BackupError(f"{target} cannot be written: {exc.strerror}") from None


def read_backup(source: Path, master_key: bytes) -> tuple[Manifest, bytes]:
    """Decrypt and check a backup. Raises ``BackupError`` on any doubt."""
    try:
        raw = source.read_bytes()
    except OSError as exc:
        raise BackupError(f"{source} cannot be read: {exc.strerror}") from None
    if not raw.startswith(MAGIC):
        raise BackupError(f"{source} is not a backup of this service")
    end = raw.find(b"\n", len(MAGIC))
    if end < 0:
        raise BackupError(f"{source} is truncated")
    header = raw[: end + 1]
    try:
        manifest = Manifest(**json.loads(raw[len(MAGIC) : end]))
    except (ValueError, TypeError):
        raise BackupError(f"{source} has an unreadable manifest") from None
    body = raw[end + 1 :]
    nonce, ciphertext = body[: cipher.NONCE_BYTES], body[cipher.NONCE_BYTES :]
    try:
        data = cipher.decrypt(_backup_key(master_key), nonce, ciphertext, header)
    except cipher.DecryptionError:
        raise BackupError(
            "the backup does not decrypt: wrong master key, or the file was altered"
        ) from None
    if hashlib.sha256(data).hexdigest() != manifest.sha256:
        raise BackupError("the backup does not match its checksum")
    try:
        schema = inspect_snapshot(data)
    except ValueError as exc:
        raise BackupError(str(exc)) from None
    if schema != manifest.schema_version:
        raise BackupError("the backup does not match its manifest")
    return manifest, data


def restore_backup(source: Path, master_key: bytes, target: Path) -> Manifest:
    """Replace the database at ``target`` with the backup. The previous file
    is kept beside it. The service must not be running."""
    manifest, data = read_backup(source, master_key)
    if manifest.schema_version > SCHEMA_VERSION:
        raise BackupError(
            f"the backup has schema {manifest.schema_version}, this version "
            f"supports up to {SCHEMA_VERSION}: update the service first"
        )
    try:
        with exclusive_lock(service_lock(target)):
            _replace(target, data)
    except LockedError:
        raise BackupError(
            "the service is running on this database: stop it first"
        ) from None
    return manifest


def _replace(target: Path, data: bytes) -> None:
    """Put ``data`` in place of the database at ``target``. The new file is
    written and migrated beside it first, so a crash on the way leaves the
    old database or the new one, never none."""
    staged = target.with_name(target.name + ".restoring")
    _remove(staged)  # from a restore that crashed
    create_private(staged, data)
    try:
        # Opening migrates an older schema forward.
        Database(staged).close()
    except BaseException:
        _remove(staged)
        raise
    if target.exists():
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        kept = target.with_name(f"{target.name}.before-restore-{stamp}")
        try:
            # A second name for the old file: the database stays in place
            # until the new one replaces it in one step.
            os.link(target, kept)
        except OSError:
            target.replace(kept)  # a file system without hard links
        # A journal left by a crash belongs to the old file. Beside the
        # restored one, SQLite would roll it into that.
        for suffix in ("-journal", "-wal", "-shm"):
            journal = target.with_name(target.name + suffix)
            if journal.exists():
                journal.replace(kept.with_name(kept.name + suffix))
    staged.replace(target)


def _remove(path: Path) -> None:
    for leftover in (path, path.with_name(path.name + "-journal")):
        leftover.unlink(missing_ok=True)


def _backup_key(master_key: bytes) -> bytes:
    return cipher.derive(master_key, _KEY_INFO)
