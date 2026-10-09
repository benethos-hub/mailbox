"""Credential encryption: cipher, key providers, and the vault that uses both.
Password hashes, and the one-time codes of a second factor.

``cryptography`` is imported in ``cipher`` only, ``keyring`` in ``keys`` only.
The backup encrypts with ``cipher``, offered as a module, as ``totp`` is.
"""

from __future__ import annotations

from . import cipher, totp
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
    "totp",
]
