"""Envelope encryption of credentials (CONCEPT 7.3).

The master key (KEK) comes from a key provider and never touches the
database. It encrypts one data key (DEK), which is stored wrapped. The DEK
encrypts every credential, each bound to its account and field.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from pydantic import SecretStr

from ...errors import ConflictError, CredentialError, SetupRequiredError
from ..ids import new_id
from ..models import CredentialInfo
from ..storage import (
    CredentialRepository,
    EncryptedCredential,
    KeyRepository,
    WrappedKey,
)
from . import cipher
from .keys import KeyProvider, encode_recovery


def _credential_aad(account_id: str, field: str) -> bytes:
    return f"credential:{account_id}:{field}".encode()


def _key_aad(key_id: str) -> bytes:
    return f"data-key:{key_id}".encode()


class CredentialVault:
    def __init__(
        self,
        keys: KeyRepository,
        credentials: CredentialRepository,
        provider: KeyProvider,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._keys = keys
        self._credentials = credentials
        self._provider = provider
        self._clock = clock
        self._dek: tuple[str, bytes] | None = None

    # --- setup ----------------------------------------------------------------

    def initialized(self) -> bool:
        return self._keys.active() is not None

    def initialize(self) -> str:
        """Create the data key, and the master key unless the provider holds
        one. Returns the recovery key, to be shown once."""
        if self.initialized():
            raise ConflictError("keys are already initialized")
        kek = self._provider.load()
        if kek is None:
            kek = cipher.new_key()
            self._provider.store(kek)
        key_id = new_id("key")
        dek = cipher.new_key()
        nonce, wrapped = cipher.encrypt(kek, dek, _key_aad(key_id))
        self._keys.add(WrappedKey(key_id, nonce, wrapped))
        self._dek = (key_id, dek)
        return encode_recovery(kek)

    def import_master_key(self, kek: bytes) -> None:
        """Store a master key from a recovery key, after checking it opens the
        data key of this database."""
        wrapped = self._keys.active()
        if wrapped is None:
            raise SetupRequiredError("no data key to open: run `keys init` instead")
        self._unwrap(kek, wrapped)
        self._provider.store(kek)

    def master_key(self) -> bytes:
        """The master key from the provider. For backups, which derive from it."""
        if not self.initialized():
            raise SetupRequiredError(
                "no keys exist yet: run `benethos-mailbox-api keys init`"
            )
        kek = self._provider.load()
        if kek is None:
            raise SetupRequiredError(
                f"no master key in {self._provider.describe()}: "
                "run `benethos-mailbox-api keys import` with the recovery key"
            )
        return kek

    def require_ready(self) -> None:
        """Raise unless credentials can be stored right now."""
        self._data_key()

    # --- credentials ----------------------------------------------------------

    def store(self, account_id: str, field: str, value: SecretStr) -> None:
        key_id, dek = self._data_key()
        aad = _credential_aad(account_id, field)
        nonce, ciphertext = cipher.encrypt(dek, value.get_secret_value().encode(), aad)
        self._credentials.put(
            EncryptedCredential(
                account_id, field, key_id, nonce, ciphertext, self._clock()
            )
        )

    def read(self, account_id: str, field: str) -> SecretStr:
        stored = self._credentials.get(account_id, field)
        if stored is None:
            raise CredentialError(f"account {account_id} has no {field}")
        _, dek = self._data_key()
        try:
            plain = cipher.decrypt(
                dek, stored.nonce, stored.ciphertext, _credential_aad(account_id, field)
            )
        except cipher.DecryptionError:
            raise CredentialError(
                f"the {field} of account {account_id} cannot be decrypted"
            ) from None
        return SecretStr(plain.decode())

    def info(self, account_id: str) -> list[CredentialInfo]:
        """Which credentials an account has, never their values."""
        return [
            CredentialInfo(field=c.field, updated_at=c.updated_at)
            for c in self._credentials.list_for_account(account_id)
        ]

    def delete(self, account_id: str) -> None:
        self._credentials.delete_for_account(account_id)

    # --- keys -----------------------------------------------------------------

    def _data_key(self) -> tuple[str, bytes]:
        if self._dek is None:
            wrapped = self._keys.active()
            if wrapped is None:
                raise SetupRequiredError(
                    "credentials cannot be stored before the keys exist: "
                    "run `benethos-mailbox-api keys init`"
                )
            self._dek = (wrapped.key_id, self._unwrap(self.master_key(), wrapped))
        return self._dek

    @staticmethod
    def _unwrap(kek: bytes, wrapped: WrappedKey) -> bytes:
        try:
            return cipher.decrypt(
                kek, wrapped.nonce, wrapped.ciphertext, _key_aad(wrapped.key_id)
            )
        except cipher.DecryptionError:
            raise CredentialError(
                "the master key does not open the data key of this database"
            ) from None
