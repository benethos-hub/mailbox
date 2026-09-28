"""Credential encryption: cipher, key providers, and the vault that uses both.

``cryptography`` is imported in ``cipher`` only, ``keyring`` in ``keys`` only.
The backup encrypts with ``cipher``, offered as a module.
"""

from __future__ import annotations

from . import cipher
from .keys import (
    EnvKeyProvider,
    FileKeyProvider,
    KeyProvider,
    KeyProviderError,
    KeyringKeyProvider,
    decode_recovery,
    encode_recovery,
)
from .passwords import PasswordHasher, Scrypt
from .vault import CredentialVault

__all__ = [
    "CredentialVault",
    "EnvKeyProvider",
    "FileKeyProvider",
    "KeyProvider",
    "KeyProviderError",
    "KeyringKeyProvider",
    "PasswordHasher",
    "Scrypt",
    "cipher",
    "decode_recovery",
    "encode_recovery",
]
