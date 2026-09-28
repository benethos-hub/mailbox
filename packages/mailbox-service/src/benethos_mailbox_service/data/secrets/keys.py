"""Where the master key (KEK) lives. The only module that imports ``keyring``.

The master key never touches the database. Every provider speaks the same
text form, the recovery key: base32 in groups of four, so what the owner
writes down is also what an environment variable or a key file holds.
"""

from __future__ import annotations

import base64
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Protocol

from ...common.chunks import batched
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

    def store(self, key: bytes, *, replace: bool = False) -> None:
        """Keep ``key``. Refuses to overwrite another key the provider
        holds, unless ``replace``: the key it holds may be the only one
        that opens some database."""
        ...

    def describe(self) -> str:
        """Where the key lives, for messages to the person at the machine."""
        ...


def encode_recovery(key: bytes) -> str:
    text = base64.b32encode(key).decode().rstrip("=")
    return "-".join(batched(text, 4))


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
        return _held(self._value, self) if self._value else None

    def store(self, key: bytes, *, replace: bool = False) -> None:
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
        try:
            if not self._path.exists():
                return None
            text = self._path.read_text(encoding="utf-8")
        except OSError as exc:
            raise KeyProviderError(f"cannot read {self._path}: {exc}") from None
        return _held(text, self)

    def store(self, key: bytes, *, replace: bool = False) -> None:
        if self._path.exists() and not replace:
            raise KeyProviderError(f"{self._path} exists, refusing to overwrite it")
        text = (encode_recovery(key) + "\n").encode("utf-8")
        try:
            if not replace:
                create_private(self._path, text)
                return
            staged = self._path.with_name(self._path.name + ".new")
            staged.unlink(missing_ok=True)
            create_private(staged, text)
            staged.replace(self._path)
        except OSError as exc:
            raise KeyProviderError(f"cannot write {self._path}: {exc}") from None

    def describe(self) -> str:
        return f"the key file {self._path}"


class KeyringKeyProvider:
    """The operating system's credential store."""

    def load(self) -> bytes | None:
        import keyring

        with _keyring_failures("read"):
            value = keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
        return _held(value, self) if value else None

    def store(self, key: bytes, *, replace: bool = False) -> None:
        import keyring

        held = None if replace else self.load()
        if held is not None and held != key:
            raise KeyProviderError(
                "the operating system's credential store holds another master "
                "key, refusing to overwrite it"
            )
        with _keyring_failures("write"):
            value = encode_recovery(key)
            keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, value)

    def describe(self) -> str:
        return "the operating system's credential store"


def _held(text: str, provider: KeyProvider) -> bytes:
    """The key a provider holds as text, or an error that names where."""
    try:
        return decode_recovery(text)
    except KeyProviderError:
        raise KeyProviderError(f"{provider.describe()} holds no recovery key") from None


@contextmanager
def _keyring_failures(action: str) -> Iterator[None]:
    """keyring has one backend per platform, each failing in its own way:
    no backend at all, a locked store, a bus that does not answer. Every one
    is the same to us: the key provider is not usable."""
    try:
        yield
    except Exception as exc:
        raise KeyProviderError(
            f"cannot {action} the operating system's credential store: {exc}"
        ) from None
