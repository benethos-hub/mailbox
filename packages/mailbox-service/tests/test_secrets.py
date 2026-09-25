from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from benethos_mailbox_service.__main__ import main
from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.models import ProviderType
from benethos_mailbox_service.data.secrets import (
    CredentialVault,
    EnvKeyProvider,
    FileKeyProvider,
    KeyProviderError,
    KeyringKeyProvider,
    cipher,
    decode_recovery,
    encode_recovery,
    keys,
)
from benethos_mailbox_service.data.storage import (
    InMemoryCredentialRepository,
    InMemoryKeyRepository,
)
from benethos_mailbox_service.errors import (
    ConflictError,
    CredentialError,
    CredentialMissingError,
    SetupRequiredError,
)
from benethos_mailbox_service.main import build_services, key_provider

from .conftest import create_account


class MemoryKeyProvider:
    def __init__(self, key: bytes | None = None) -> None:
        self.key = key

    def load(self) -> bytes | None:
        return self.key

    def store(self, key: bytes) -> None:
        self.key = key

    def describe(self) -> str:
        return "memory"


def vault(provider: MemoryKeyProvider | None = None) -> CredentialVault:
    return CredentialVault(
        InMemoryKeyRepository(),
        InMemoryCredentialRepository(),
        provider or MemoryKeyProvider(),
    )


# --- cipher and recovery key ------------------------------------------------


def test_cipher_round_trip_and_tamper() -> None:
    key = cipher.new_key()
    nonce, ciphertext = cipher.encrypt(key, b"secret", b"aad")
    assert cipher.decrypt(key, nonce, ciphertext, b"aad") == b"secret"
    with pytest.raises(cipher.DecryptionError):
        cipher.decrypt(key, nonce, ciphertext, b"other aad")
    with pytest.raises(cipher.DecryptionError):
        cipher.decrypt(cipher.new_key(), nonce, ciphertext, b"aad")
    tampered = bytes([ciphertext[0] ^ 1]) + ciphertext[1:]
    with pytest.raises(cipher.DecryptionError):
        cipher.decrypt(key, nonce, tampered, b"aad")
    # Truncated: a nonce or a ciphertext of the wrong length.
    with pytest.raises(cipher.DecryptionError):
        cipher.decrypt(key, nonce[:5], ciphertext, b"aad")
    with pytest.raises(cipher.DecryptionError):
        cipher.decrypt(key, nonce, ciphertext[:3], b"aad")


def test_derive_is_stable_and_separate() -> None:
    key = cipher.new_key()
    assert cipher.derive(key, b"a") == cipher.derive(key, b"a")
    assert cipher.derive(key, b"a") != cipher.derive(key, b"b")


def test_recovery_key_round_trip() -> None:
    key = cipher.new_key()
    text = encode_recovery(key)
    assert all(len(group) <= 4 for group in text.split("-"))
    assert decode_recovery(text) == key
    assert decode_recovery(" " + text.lower().replace("-", " ") + "\n") == key


@pytest.mark.parametrize("text", ["not base32!", "ABCD-EFGH"])
def test_recovery_key_rejects_garbage(text: str) -> None:
    with pytest.raises(KeyProviderError, match="not a recovery key"):
        decode_recovery(text)


# --- key providers ------------------------------------------------------------


def test_env_provider() -> None:
    key = cipher.new_key()
    assert EnvKeyProvider(encode_recovery(key)).load() == key
    assert EnvKeyProvider(None).load() is None
    with pytest.raises(KeyProviderError):
        EnvKeyProvider(None).store(key)
    assert "MAILBOX_SERVICE_MASTER_KEY" in EnvKeyProvider(None).describe()


def test_file_provider(tmp_path: Path) -> None:
    provider = FileKeyProvider(tmp_path / "secrets" / "master.key")
    assert provider.load() is None
    key = cipher.new_key()
    provider.store(key)
    assert provider.load() == key
    with pytest.raises(KeyProviderError, match="refusing"):
        provider.store(key)
    assert "master.key" in provider.describe()
    # A path that cannot be read or written is the provider's failure.
    folder = FileKeyProvider(tmp_path / "secrets")
    with pytest.raises(KeyProviderError, match="cannot read"):
        folder.load()
    with pytest.raises(KeyProviderError, match="cannot write"):
        FileKeyProvider(tmp_path / "secrets" / "master.key" / "x").store(key)


def test_keyring_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    import keyring

    stored: dict[tuple[str, str], str] = {}
    monkeypatch.setattr(keyring, "get_password", lambda s, u: stored.get((s, u)))
    monkeypatch.setattr(
        keyring, "set_password", lambda s, u, v: stored.__setitem__((s, u), v)
    )
    provider = KeyringKeyProvider()
    assert provider.load() is None
    key = cipher.new_key()
    provider.store(key)
    assert stored[(keys.KEYRING_SERVICE, keys.KEYRING_USERNAME)] == encode_recovery(key)
    assert provider.load() == key
    assert "credential store" in provider.describe()


def test_keyring_failures_are_the_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    import keyring
    from keyring.errors import NoKeyringError

    def none(*args: object) -> None:
        raise NoKeyringError("No recommended backend was available")

    monkeypatch.setattr(keyring, "get_password", none)
    monkeypatch.setattr(keyring, "set_password", none)
    provider = KeyringKeyProvider()
    with pytest.raises(KeyProviderError, match="cannot read .* No recommended"):
        provider.load()
    with pytest.raises(KeyProviderError, match="cannot write"):
        provider.store(cipher.new_key())


def test_key_provider_from_settings(tmp_path: Path) -> None:
    assert isinstance(
        key_provider(Settings(key_provider="keyring")), KeyringKeyProvider
    )
    assert isinstance(
        key_provider(Settings(key_provider="file", key_file=tmp_path / "k")),
        FileKeyProvider,
    )
    assert isinstance(key_provider(Settings(key_provider="env")), EnvKeyProvider)
    with pytest.raises(KeyProviderError, match="KEY_FILE"):
        key_provider(Settings(key_provider="file"))


# --- the vault ----------------------------------------------------------------


def test_vault_round_trip() -> None:
    v = vault()
    assert not v.initialized()
    recovery = v.initialize()
    assert v.initialized()
    assert decode_recovery(recovery) == v.master_key()
    v.store("acc_1", "password", SecretStr("hunter2"))
    assert v.read("acc_1", "password").get_secret_value() == "hunter2"
    assert [i.field for i in v.info("acc_1")] == ["password"]
    v.delete("acc_1")
    assert v.info("acc_1") == []
    with pytest.raises(CredentialMissingError, match="has no password"):
        v.read("acc_1", "password")


def test_vault_initializes_once() -> None:
    v = vault()
    v.initialize()
    with pytest.raises(ConflictError):
        v.initialize()


def test_vault_reuses_a_master_key_the_provider_holds() -> None:
    key = cipher.new_key()
    v = vault(MemoryKeyProvider(key))
    assert decode_recovery(v.initialize()) == key


def test_vault_needs_keys_before_storing() -> None:
    with pytest.raises(SetupRequiredError, match="keys init"):
        vault().store("acc_1", "password", SecretStr("x"))


def test_vault_without_master_key_asks_for_import() -> None:
    provider = MemoryKeyProvider()
    keys_repo, creds = InMemoryKeyRepository(), InMemoryCredentialRepository()
    CredentialVault(keys_repo, creds, provider).initialize()
    provider.key = None
    fresh = CredentialVault(keys_repo, creds, provider)
    with pytest.raises(SetupRequiredError, match="keys import"):
        fresh.store("acc_1", "password", SecretStr("x"))


def test_vault_rejects_a_wrong_master_key() -> None:
    provider = MemoryKeyProvider()
    keys_repo, creds = InMemoryKeyRepository(), InMemoryCredentialRepository()
    CredentialVault(keys_repo, creds, provider).initialize()
    provider.key = cipher.new_key()
    with pytest.raises(CredentialError, match="does not open"):
        CredentialVault(keys_repo, creds, provider).store(
            "acc_1", "password", SecretStr("x")
        )


def test_a_credential_moved_to_another_account_does_not_decrypt() -> None:
    keys_repo, creds = InMemoryKeyRepository(), InMemoryCredentialRepository()
    v = CredentialVault(keys_repo, creds, MemoryKeyProvider())
    v.initialize()
    v.store("acc_1", "password", SecretStr("hunter2"))
    stolen = creds.get("acc_1", "password")
    assert stolen is not None
    creds.put(
        type(stolen)(
            "acc_2",
            "password",
            stolen.key_id,
            stolen.nonce,
            stolen.ciphertext,
            stolen.updated_at,
        )
    )
    with pytest.raises(CredentialError, match="cannot be decrypted"):
        v.read("acc_2", "password")


def test_import_master_key() -> None:
    provider = MemoryKeyProvider()
    keys_repo, creds = InMemoryKeyRepository(), InMemoryCredentialRepository()
    recovery = CredentialVault(keys_repo, creds, provider).initialize()
    provider.key = None
    fresh = CredentialVault(keys_repo, creds, provider)
    with pytest.raises(CredentialError):
        fresh.import_master_key(cipher.new_key())
    fresh.import_master_key(decode_recovery(recovery))
    assert provider.key == decode_recovery(recovery)
    with pytest.raises(SetupRequiredError, match="keys init"):
        vault().import_master_key(cipher.new_key())


# --- through the service and the API ----------------------------------------------


def test_stored_encrypted_and_never_returned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    master = encode_recovery(cipher.new_key())
    monkeypatch.setenv("MAILBOX_SERVICE_MASTER_KEY", master)
    settings = Settings(data_dir=tmp_path, storage="sqlite", api_key=SecretStr("k"))
    services = build_services(settings)
    services.vault.initialize()
    account = create_account(
        services.accounts,
        ProviderType.MEMORY,
        "a@example.com",
        credentials={"password": SecretStr("hunter2")},
    )
    assert [c.field for c in account.credentials] == ["password"]
    assert "hunter2" not in account.model_dump_json()
    services.close()

    raw = sqlite3.connect(settings.database_path)
    dump = "\n".join(raw.iterdump())
    raw.close()
    assert "hunter2" not in dump

    again = build_services(settings)
    assert again.vault.read(account.id, "password").get_secret_value() == "hunter2"
    again.close()


def test_api_refuses_credentials_before_keys_exist(client: TestClient) -> None:
    response = client.post(
        "/v1/accounts",
        json={
            "provider": "memory",
            "email": "a@example.com",
            "credentials": {"password": "hunter2"},
        },
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "setup_required"
    assert client.get("/v1/accounts").json() == []


def test_keys_init_and_import_commands(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    key_file = tmp_path / "master.key"
    monkeypatch.setenv("MAILBOX_SERVICE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MAILBOX_SERVICE_STORAGE", "sqlite")
    monkeypatch.setenv("MAILBOX_SERVICE_KEY_PROVIDER", "file")
    monkeypatch.setenv("MAILBOX_SERVICE_KEY_FILE", str(key_file))
    assert main(["keys", "init"]) == 0
    out, err = capsys.readouterr()
    recovery = out.strip()
    assert "shown this once" in err
    assert decode_recovery(recovery) == FileKeyProvider(key_file).load()

    key_file.unlink()
    monkeypatch.setattr("sys.stdin", _Stdin(recovery + "\n"))
    assert main(["keys", "import"]) == 0
    assert FileKeyProvider(key_file).load() == decode_recovery(recovery)


def test_a_generated_key_as_a_container_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``keys generate`` prints a key and stores nothing. Saved as the key
    file, ``keys init`` uses it and only adds the data key."""
    monkeypatch.setenv("MAILBOX_SERVICE_DATA_DIR", str(tmp_path / "data"))
    assert main(["keys", "generate"]) == 0
    generated = capsys.readouterr().out.strip()
    assert not (tmp_path / "data").exists()
    key_file = tmp_path / "secrets" / "master_key"
    key_file.parent.mkdir()
    key_file.write_text(generated + "\n", encoding="utf-8")
    key_file.chmod(0o400)  # a secret is mounted read-only
    monkeypatch.setenv("MAILBOX_SERVICE_STORAGE", "sqlite")
    monkeypatch.setenv("MAILBOX_SERVICE_KEY_PROVIDER", "file")
    monkeypatch.setenv("MAILBOX_SERVICE_KEY_FILE", str(key_file))
    assert main(["keys", "init"]) == 0
    assert capsys.readouterr().out.strip() == generated
    assert main(["keys", "generate"]) == 0
    assert capsys.readouterr().out.strip() != generated


class _Stdin:
    def __init__(self, text: str) -> None:
        self._text = text

    def isatty(self) -> bool:
        return False

    def readline(self) -> str:
        return self._text
