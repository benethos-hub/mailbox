"""Where the master key (KEK) lives. The only module that imports ``keyring``.

The master key never touches the database. Every provider speaks the same
text form, the recovery key: base32 in groups of four, so what the owner
writes down is also what an environment variable or a key file holds.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Protocol

from ..files import create_private
from .cipher import KEY_BYTES

KEYRING_SERVICE = "benethos-mailbox-service"
KEYRING_USERNAME = "master-key"


class KeyProviderError(Exception):
    """The provider cannot hold or hand out a key."""


class KeyProvider(Protocol):
    def load(self) -> bytes | None:
        """The master key, or ``None`` if this provider holds none."""
        ...

    def store(self, key: bytes) -> None: ...

    def describe(self) -> str:
        """Where the key lives, for messages to the person at the machine."""
        ...


def encode_recovery(key: bytes) -> str:
    text = base64.b32encode(key).decode().rstrip("=")
    return "-".join(text[i : i + 4] for i in range(0, len(text), 4))


def decode_recovery(text: str) -> bytes:
    compact = "".join(text.split()).replace("-", "").upper()
    compact += "=" * (-len(compact) % 8)
    try:
        key = base64.b32decode(compact)
    except ValueError:
        raise KeyProviderError("not a recovery key") from None
    if len(key) != KEY_BYTES:
        raise KeyProviderError("not a recovery key")
    return key


class EnvKeyProvider:
    """``MAILBOX_SERVICE_MASTER_KEY`` holds the recovery key. Read only."""

    def __init__(self, value: str | None) -> None:
        self._value = value

    def load(self) -> bytes | None:
        return decode_recovery(self._value) if self._value else None

    def store(self, key: bytes) -> None:
        raise KeyProviderError(
            "the env key provider cannot store a key: set MAILBOX_SERVICE_MASTER_KEY "
            "to the recovery key instead"
        )

    def describe(self) -> str:
        return "the environment variable MAILBOX_SERVICE_MASTER_KEY"


class FileKeyProvider:
    """A file readable by the service user only, e.g. a container secret."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> bytes | None:
        if not self._path.exists():
            return None
        return decode_recovery(self._path.read_text(encoding="utf-8"))

    def store(self, key: bytes) -> None:
        if self._path.exists():
            raise KeyProviderError(f"{self._path} exists, refusing to overwrite it")
        create_private(self._path, (encode_recovery(key) + "\n").encode("utf-8"))

    def describe(self) -> str:
        return f"the key file {self._path}"


class KeyringKeyProvider:
    """The operating system's credential store."""

    def load(self) -> bytes | None:
        import keyring

        value = keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
        return decode_recovery(value) if value else None

    def store(self, key: bytes) -> None:
        import keyring

        keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, encode_recovery(key))

    def describe(self) -> str:
        return "the operating system's credential store"
