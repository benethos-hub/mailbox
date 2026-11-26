"""The file of a backup in blocks, and their encryption (CONCEPT 7.8).

After a magic line and a manifest line, the plain bytes of a backup in
blocks of ``BLOCK`` bytes. Each block is written as its nonce, a byte
that marks the last block, the length of its ciphertext and the
ciphertext. Every block is encrypted with a key derived from the master
key and authenticated with the magic, the manifest, its number and its
mark, so no block can be altered, moved, dropped or added unnoticed, and
neither can the header. No more than one block is in memory at a time.
Version 1 holds the database as one ciphertext, authenticated with the
magic and the manifest.
"""

from __future__ import annotations

import hashlib
import io
from collections.abc import Iterator
from pathlib import Path
from typing import Any, BinaryIO

from benethos_mailbox_common.values import sizes

from ..secrets import cipher

MAGIC = b"MAILBOX-SERVICE-BACKUP 2\n"

MAGIC_1 = b"MAILBOX-SERVICE-BACKUP 1\n"

MAGIC_3 = b"MAILBOX-SERVICE-BACKUP 3\n"

BLOCK = sizes.MIB

KEY_INFO = b"mailbox-service backup v1"

LENGTH_BYTES = 4

# A ciphertext holds its block and the tag of AES-GCM.
LONGEST_SEALED = BLOCK + 16


class BackupError(Exception):
    """A backup that cannot be read, decrypted or restored."""


class Decrypting(io.RawIOBase):
    """The plain bytes of a backup in blocks, each block decrypted and
    checked as it is read, one in memory at a time. ``finish`` reads the
    rest and checks the whole against the checksum of the manifest: what
    was read before that is to be thrown away when it fails."""

    def __init__(self, file: BinaryIO, header: bytes, key: bytes, source: Path):
        super().__init__()
        self._file = file
        self._header = header
        self._key = key
        self._source = source
        self._index = 0
        self._block = memoryview(b"")
        self._last = False
        self._digest = hashlib.sha256()

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: Any) -> int:
        while not self._block and not self._last:
            self._next()
        count = min(len(buffer), len(self._block))
        buffer[:count] = self._block[:count]
        self._block = self._block[count:]
        return count

    def _next(self) -> None:
        source = self._source
        nonce = exactly(self._file, cipher.NONCE_BYTES, source)
        last = exactly(self._file, 1, source) == mark(True)
        length = int.from_bytes(exactly(self._file, LENGTH_BYTES, source), "big")
        if length > LONGEST_SEALED:
            raise BackupError(f"{source} is damaged")
        sealed = exactly(self._file, length, source)
        block = opened(self._key, nonce, sealed, aad(self._header, self._index, last))
        self._digest.update(block)
        self._block = memoryview(block)
        self._last = last
        self._index += 1
        if last and self._file.read(1):
            raise BackupError(f"{source} holds more than its backup")

    def finish(self, sha256: str) -> None:
        """Read to the end of the backup and hold it to ``sha256``."""
        while not self._last:
            self._next()
        if self._block or self._digest.hexdigest() != sha256:
            raise BackupError("the backup does not match its checksum")


def decrypt(
    file: BinaryIO, header: bytes, key: bytes, out: BinaryIO, source: Path
) -> str:
    """Write the database the backup holds to ``out``. Returns its SHA-256."""
    digest = hashlib.sha256()
    if header.startswith(MAGIC_1):
        body = file.read()
        nonce, ciphertext = body[: cipher.NONCE_BYTES], body[cipher.NONCE_BYTES :]
        data = opened(key, nonce, ciphertext, header)
        out.write(data)
        digest.update(data)
        return digest.hexdigest()
    index = 0
    while True:
        nonce = exactly(file, cipher.NONCE_BYTES, source)
        last = exactly(file, 1, source) == mark(True)
        length = int.from_bytes(exactly(file, LENGTH_BYTES, source), "big")
        if length > LONGEST_SEALED:
            raise BackupError(f"{source} is damaged")
        sealed = exactly(file, length, source)
        block = opened(key, nonce, sealed, aad(header, index, last))
        out.write(block)
        digest.update(block)
        if last:
            break
        index += 1
    if file.read(1):
        raise BackupError(f"{source} holds more than its backup")
    return digest.hexdigest()


def opened(key: bytes, nonce: bytes, sealed: bytes, aad: bytes) -> bytes:
    try:
        return cipher.decrypt(key, nonce, sealed, aad)
    except cipher.DecryptionError:
        raise BackupError(
            "the backup does not decrypt: wrong master key, or the file was altered"
        ) from None


def exactly(file: BinaryIO, size: int, source: Path) -> bytes:
    data = file.read(size)
    if len(data) != size:
        raise BackupError(f"{source} is truncated")
    return data


def blocks_of(file: BinaryIO) -> Iterator[tuple[int, bytes, bool]]:
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


def aad(header: bytes, index: int, last: bool) -> bytes:
    return header + index.to_bytes(8, "big") + mark(last)


def mark(last: bool) -> bytes:
    return b"\x01" if last else b"\x00"


def length(size: int) -> bytes:
    return size.to_bytes(LENGTH_BYTES, "big")


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while block := file.read(BLOCK):
            digest.update(block)
    return digest.hexdigest()


def backup_key(master_key: bytes) -> bytes:
    return cipher.derive(master_key, KEY_INFO)
