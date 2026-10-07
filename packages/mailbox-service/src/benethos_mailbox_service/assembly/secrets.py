"""The master key: which key provider the settings name, and the vault
of the credentials behind it."""

from __future__ import annotations

from ..config import Settings
from ..data.secrets import (
    CredentialVault,
    EnvKeyProvider,
    FileKeyProvider,
    KeyProvider,
    KeyProviderError,
    KeyringKeyProvider,
)
from ..data.storage import Repositories
from ..domain.activity import SERVICE, ActivityLog
from ..domain.activity import system as said


def key_provider(
    settings: Settings, activity: ActivityLog | None = None
) -> KeyProvider:
    """The key provider the settings name."""
    if settings.key_provider == "env":
        (activity or ActivityLog()).record(said.MasterKeyFromEnvironment(by=SERVICE))
        value = settings.master_key.get_secret_value() if settings.master_key else None
        return EnvKeyProvider(value)
    if settings.key_provider == "file":
        if settings.key_file is None:
            raise KeyProviderError(
                "MAILBOX_SERVICE_KEY_FILE must be set for the file key provider. "
                "`benethos-mailbox-service paths` suggests one"
            )
        if settings.key_file.resolve().is_relative_to(settings.data_dir.resolve()):
            # A copy or a backup of the data folder would carry the key to
            # the credentials with them (CONCEPT 7.4).
            raise KeyProviderError(
                f"the key file {settings.key_file} lies in the data folder "
                f"{settings.data_dir}. Keep it apart, e.g. in the config folder "
                "that `benethos-mailbox-service paths` names"
            )
        return FileKeyProvider(settings.key_file)
    return KeyringKeyProvider()


def vault(
    repositories: Repositories,
    settings: Settings,
    activity: ActivityLog,
    keys: KeyProvider | None = None,
) -> CredentialVault:
    """The vault of the credentials, under ``keys``, else under the key
    provider the settings name."""
    return CredentialVault(
        repositories.keys,
        repositories.credentials,
        keys or key_provider(settings, activity),
    )
