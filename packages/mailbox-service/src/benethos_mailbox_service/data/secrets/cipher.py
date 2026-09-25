"""AES-256-GCM and key derivation. The only module that imports ``cryptography``."""

from __future__ import annotations

import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

KEY_BYTES = 32
NONCE_BYTES = 12


class DecryptionError(Exception):
    """Wrong key, wrong associated data, tampered or truncated ciphertext."""


def new_key() -> bytes:
    return AESGCM.generate_key(bit_length=KEY_BYTES * 8)


def encrypt(key: bytes, plaintext: bytes, aad: bytes) -> tuple[bytes, bytes]:
    """A fresh random nonce and the ciphertext, authenticated with ``aad``."""
    nonce = os.urandom(NONCE_BYTES)
    return nonce, AESGCM(key).encrypt(nonce, plaintext, aad)


def decrypt(key: bytes, nonce: bytes, ciphertext: bytes, aad: bytes) -> bytes:
    # A nonce or a ciphertext of the wrong length is a ValueError to the
    # library, a damaged record to us.
    try:
        return AESGCM(key).decrypt(nonce, ciphertext, aad)
    except (InvalidTag, ValueError):
        raise DecryptionError("decryption failed") from None


def derive(key: bytes, info: bytes) -> bytes:
    """A separate key for another purpose, derived from ``key``."""
    return HKDF(
        algorithm=hashes.SHA256(), length=KEY_BYTES, salt=None, info=info
    ).derive(key)
