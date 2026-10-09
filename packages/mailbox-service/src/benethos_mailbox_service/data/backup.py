"""Encrypted backups of the whole database (CONCEPT 7.8).

File layout, version 2: a magic line, a JSON manifest line, then the
database in blocks of ``BLOCK`` bytes. Each block is written as its nonce,
a byte that marks the last block, the length of its ciphertext and the
ciphertext. Every block is encrypted with a key derived from the master
key and authenticated with the magic, the manifest, its number and its
mark, so no block can be altered, moved, dropped or added unnoticed, and
neither can the header. A backup is written from a copy of the database
on disk and read back into a file, so no more than one block is in
memory at a time.

Version 1 holds the database as one ciphertext, authenticated with the
magic and the manifest. It is still read. The master key itself is never
in a backup.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import BinaryIO

from benethos_mailbox_common.sizes import MIB

from ..common.clock import iso, utc_now
from .files import LockedError, create_private, exclusive_lock
from .secrets import cipher
from .storage import SCHEMA_VERSION, Store, inspect_file, migrate_file, service_lock

MAGIC = b"MAILBOX-SERVICE-BACKUP 2\n"
MAGIC_1 = b"MAILBOX-SERVICE-BACKUP 1\n"
BLOCK = MIB
_KEY_INFO = b"mailbox-service backup v1"
# The longest manifest line read: it holds four short fields.
_MANIFEST_BYTES = 4096
_LENGTH_BYTES = 4
# A ciphertext holds its block and the tag of AES-GCM.
_LONGEST_SEALED = BLOCK + 16


class BackupError(Exception):
    """A backup that cannot be read, decrypted or restored."""


@dataclass(frozen=True)
class Manifest:
    service_version: str
    schema_version: int
    created_at: str
    sha256: str


def create_backup(
    store: Store, master_key: bytes, target: Path, service_version: str
) -> Manifest:
    if target.exists():
        raise BackupError(f"{target} exists, refusing to overwrite it")
    with store.snapshot_file() as snapshot:
        try:
            schema_version = inspect_file(snapshot)
        except ValueError as exc:
            raise BackupError(f"the database cannot be backed up: {exc}") from None
        manifest = Manifest(
            service_version=service_version,
            schema_version=schema_version,
            created_at=iso(utc_now()),
            sha256=_sha256(snapshot),
        )
        write_backup(snapshot, manifest, master_key, target)
    return manifest


def write_backup(
    source: Path, manifest: Manifest, master_key: bytes, target: Path
) -> None:
    """The database file at ``source`` as a backup at ``target``, block by
    block. A backup that cannot be finished is removed."""
    header = MAGIC + json.dumps(asdict(manifest)).encode() + b"\n"
    key = _backup_key(master_key)
    try:
        create_private(target, header)
    except OSError as exc:
        raise BackupError(f"{target} cannot be written: {exc.strerror}") from None
    try:
        with source.open("rb") as plain, target.open("ab") as out:
            for index, block, last in _blocks(plain):
                nonce, sealed = cipher.encrypt(key, block, _aad(header, index, last))
                out.write(nonce + _mark(last) + _length(len(sealed)) + sealed)
    except OSError as exc:
        target.unlink(missing_ok=True)
        raise BackupError(f"{target} cannot be written: {exc.strerror}") from None
    except BaseException:
        target.unlink(missing_ok=True)
        raise


def read_backup(source: Path, master_key: bytes, into: Path) -> Manifest:
    """Decrypt and check a backup into a new file at ``into``, readable by
    its owner alone. Raises ``BackupError`` on any doubt, and leaves no
    file at ``into`` then."""
    try:
        file = source.open("rb")
    except OSError as exc:
        raise BackupError(f"{source} cannot be read: {exc.strerror}") from None
    with file:
        header, manifest = _header(file, source)
        try:
            create_private(into)
        except OSError as exc:
            raise BackupError(f"{into} cannot be written: {exc.strerror}") from None
        try:
            with into.open("ab") as out:
                digest = _decrypt(file, header, _backup_key(master_key), out, source)
            if digest != manifest.sha256:
                raise BackupError("the backup does not match its checksum")
            try:
                schema = inspect_file(into)
            except ValueError as exc:
                raise BackupError(str(exc)) from None
            if schema != manifest.schema_version:
                raise BackupError("the backup does not match its manifest")
        except OSError as exc:
            into.unlink(missing_ok=True)
            raise BackupError(f"{source} cannot be read: {exc.strerror}") from None
        except BaseException:
            into.unlink(missing_ok=True)
            raise
    return manifest


def verify_backup(source: Path, master_key: bytes, scratch: Path) -> Manifest:
    """``read_backup`` into ``scratch``, which is removed afterwards."""
    try:
        return read_backup(source, master_key, scratch)
    finally:
        scratch.unlink(missing_ok=True)


def restore_backup(source: Path, master_key: bytes, target: Path) -> Manifest:
    """Replace the database at ``target`` with the backup. The previous file
    is kept beside it. The service must not be running."""
    staged = target.with_name(target.name + ".restoring")
    try:
        with exclusive_lock(service_lock(target)):
            _remove(staged)  # from a restore that crashed
            manifest = read_backup(source, master_key, staged)
            if manifest.schema_version > SCHEMA_VERSION:
                _remove(staged)
                raise BackupError(
                    f"the backup has schema {manifest.schema_version}, this "
                    f"version supports up to {SCHEMA_VERSION}: update the "
                    "service first"
                )
            _replace(target, staged)
    except LockedError:
        raise BackupError(
            "the service is running on this database: stop it first"
        ) from None
    return manifest


def _header(file: BinaryIO, source: Path) -> tuple[bytes, Manifest]:
    """The magic and the manifest line, and the manifest."""
    magic = file.readline(len(MAGIC))
    if magic not in (MAGIC, MAGIC_1):
        raise BackupError(f"{source} is not a backup of this service")
    line = file.readline(_MANIFEST_BYTES)
    if not line.endswith(b"\n"):
        raise BackupError(f"{source} is truncated")
    try:
        manifest = Manifest(**json.loads(line))
    except (ValueError, TypeError):
        raise BackupError(f"{source} has an unreadable manifest") from None
    return magic + line, manifest


def _decrypt(
    file: BinaryIO, header: bytes, key: bytes, out: BinaryIO, source: Path
) -> str:
    """Write the database the backup holds to ``out``. Returns its SHA-256."""
    digest = hashlib.sha256()
    if header.startswith(MAGIC_1):
        body = file.read()
        nonce, ciphertext = body[: cipher.NONCE_BYTES], body[cipher.NONCE_BYTES :]
        data = _opened(key, nonce, ciphertext, header)
        out.write(data)
        digest.update(data)
        return digest.hexdigest()
    index = 0
    while True:
        nonce = _exactly(file, cipher.NONCE_BYTES, source)
        last = _exactly(file, 1, source) == _mark(True)
        length = int.from_bytes(_exactly(file, _LENGTH_BYTES, source), "big")
        if length > _LONGEST_SEALED:
            raise BackupError(f"{source} is damaged")
        sealed = _exactly(file, length, source)
        block = _opened(key, nonce, sealed, _aad(header, index, last))
        out.write(block)
        digest.update(block)
        if last:
            break
        index += 1
    if file.read(1):
        raise BackupError(f"{source} holds more than its backup")
    return digest.hexdigest()


def _opened(key: bytes, nonce: bytes, sealed: bytes, aad: bytes) -> bytes:
    try:
        return cipher.decrypt(key, nonce, sealed, aad)
    except cipher.DecryptionError:
        raise BackupError(
            "the backup does not decrypt: wrong master key, or the file was altered"
        ) from None


def _exactly(file: BinaryIO, size: int, source: Path) -> bytes:
    data = file.read(size)
    if len(data) != size:
        raise BackupError(f"{source} is truncated")
    return data


def _blocks(file: BinaryIO) -> Iterator[tuple[int, bytes, bool]]:
    """Each block of the file with its number and whether it is the last.
    A file that is empty is one empty block."""
    block = file.read(BLOCK)
    index = 0
    while True:
        after = file.read(BLOCK)
        yield index, block, not after
        if not after:
            return
        block, index = after, index + 1


def _aad(header: bytes, index: int, last: bool) -> bytes:
    return header + index.to_bytes(8, "big") + _mark(last)


def _mark(last: bool) -> bytes:
    return b"\x01" if last else b"\x00"


def _length(size: int) -> bytes:
    return size.to_bytes(_LENGTH_BYTES, "big")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while block := file.read(BLOCK):
            digest.update(block)
    return digest.hexdigest()


def _replace(target: Path, staged: Path) -> None:
    """Put the database at ``staged`` in place of the one at ``target``.
    It is migrated beside it first, so a crash on the way leaves the old
    database or the new one, never none."""
    try:
        migrate_file(staged)
    except BaseException:
        _remove(staged)
        raise
    if target.exists():
        stamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
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
