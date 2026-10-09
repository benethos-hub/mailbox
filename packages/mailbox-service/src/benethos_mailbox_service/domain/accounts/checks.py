"""What an account's settings and credentials must pass before they are
stored: a display name on one line, no secret among the settings, every
host one the service may connect to, and a login with a throwaway
adapter.

``AccountService`` decides when each check runs and stores what passed.
"""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import SecretStr

from benethos_mailbox_common import redact

from ...common.hosts import is_server
from ...common.text import has_break
from ...data.models import Account, ProviderType
from ...data.protocols import HostCheck
from ...data.providers import (
    CredentialReader,
    ProviderSettings,
    Tokens,
    hosts_in,
)
from ...errors import BadRequestError, MailboxServiceError
from .adapters import REFRESH_TOKEN, Adapters

# The display name goes into the From of every send, on one line, and
# into the log. No line break, no other control character.
LONGEST_NAME = 200

# Settings are returned to callers. A secret belongs in the credentials,
# which never are.
_SECRET_WORDS = ("password", "secret", "token", "credential", "apikey", "api_key")


class AccountChecks:
    """The checks that reach out: the hosts of the settings, and a login.
    Without ``check_host``, every host that is a name or an address
    passes."""

    def __init__(self, adapters: Adapters, check_host: HostCheck | None) -> None:
        self._adapters = adapters
        # Every host in an account's settings passes this before the first
        # connection: the service must not be pointed into its own network.
        self._check_host = check_host

    async def login(
        self,
        provider: ProviderType,
        settings: ProviderSettings,
        read: CredentialReader,
        secrets: dict[str, SecretStr],
        signed_in: Tokens | None = None,
    ) -> None:
        """Log in once with a throwaway adapter. A refresh token it is
        handed lands in ``secrets``, to be stored with the rest."""
        for value in secrets.values():
            # Typed in just now: a failed login must not show it.
            redact.note(value.get_secret_value())
        probe = self._adapters.build(
            provider,
            settings,
            read,
            lambda value: secrets.__setitem__(REFRESH_TOKEN, value),
            signed_in,
        )
        try:
            await probe.verify()
        finally:
            await probe.close()

    async def hosts(self, settings: Mapping[str, object]) -> None:
        """Refuse settings that point the service at a host it may not
        connect to, before any adapter is built: ``host``, ``smtp_host`` and
        any other ``*_host``. A host that is no name and no address is
        refused before it is looked up. Without a check, every other host
        passes."""
        for named in hosts_in(settings):
            if not is_server(named.host):
                raise BadRequestError(
                    f"{named.key} is not a host name or an IP address"
                )
        if self._check_host is None:
            return
        for named in hosts_in(settings):
            try:
                address = await self._check_host(named.host, named.port)
            except MailboxServiceError as exc:
                raise BadRequestError(exc.message) from None
            if address is None:
                raise BadRequestError(f"{named.key}: {named.host} does not resolve")


def one_line_name(name: str | None) -> None:
    if name is None:
        return
    if len(name) > LONGEST_NAME:
        raise BadRequestError(
            f"the display name is longer than {LONGEST_NAME} characters"
        )
    if has_break(name):
        raise BadRequestError(
            "the display name must not hold a line break or a control character"
        )


def merge_settings(
    before: dict[str, str | int | bool],
    defaults: Mapping[str, str | int | bool],
    settings: Mapping[str, str | int | bool | None],
) -> dict[str, str | int | bool]:
    """The settings with the changes. A setting removed falls back to
    what the provider assumes."""
    result = dict(before)
    for key, value in settings.items():
        if value is None:
            result.pop(key, None)
            if key in defaults:
                result[key] = defaults[key]
        else:
            result[key] = value
    return result


def what_changed(
    account: Account,
    display_name: str | None,
    rename: bool,
    changed: bool,
    secrets: Mapping[str, SecretStr],
) -> list[str]:
    """What an update changes, for the audit: never a secret's value."""
    what = []
    if rename and display_name != account.display_name:
        what.append("display name")
    if changed:
        what.append("settings")
    return what + sorted(secrets)


def no_secrets_in(settings: Mapping[str, object] | None) -> None:
    for key in settings or {}:
        if any(word in key.lower().replace("-", "_") for word in _SECRET_WORDS):
            raise BadRequestError(
                f"{key} looks like a secret: pass it in credentials, which are "
                "stored encrypted and never returned, not in settings"
            )


def pending(secrets: Mapping[str, SecretStr], field: str) -> SecretStr:
    try:
        return secrets[field]
    except KeyError:
        raise BadRequestError(f"the account needs the credential {field}") from None
