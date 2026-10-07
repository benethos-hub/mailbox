"""What the commands share: the option ``--env-file``, the errors a
command reports instead of a trace, and the master key from the key
provider or from a recovery key."""

from __future__ import annotations

import argparse
import getpass
import sys

from ..config import ENV_FILE, Settings

# The subparsers of the command line, as argparse hands them out.
Commands = argparse._SubParsersAction

ENV_FILE_HELP = (
    f"the settings file, else MAILBOX_SERVICE_ENV_FILE, else {ENV_FILE} where "
    "the working directory has the repository's folders, else the config "
    "folder of the operating system. Relative paths in it count from its "
    "folder. `paths` names the folders that apply."
)


class UsageError(Exception):
    """A command used the wrong way."""


def stored(settings: Settings, what: str) -> Settings:
    """``settings``, if they keep what the command writes: in memory it
    would vanish with the command."""
    if settings.storage != "sqlite":
        raise UsageError(f"{what} need MAILBOX_SERVICE_STORAGE=sqlite")
    return settings


def master_key(settings: Settings) -> bytes:
    """The master key the key provider of ``settings`` holds."""
    from ..assembly import key_provider

    provider = key_provider(settings)
    key = provider.load()
    if key is None:
        raise UsageError(f"no master key in {provider.describe()}: pass --recovery-key")
    return key


def read_recovery_key() -> bytes:
    """A recovery key from the terminal, unseen, or from stdin."""
    from ..data.secrets import decode_recovery

    text = (
        getpass.getpass("Recovery key: ")
        if sys.stdin.isatty()
        else sys.stdin.readline()
    )
    return decode_recovery(text)


def expected() -> tuple[type[BaseException], ...]:
    """What a command reports as an error and a return code, not a trace:
    its own usage, a key or backup that cannot be read, the service's
    errors, and settings that do not validate."""
    from pydantic import ValidationError

    from ..data.backup import BackupError
    from ..data.secrets import KeyProviderError
    from ..errors import MailboxServiceError

    return (
        UsageError,
        BackupError,
        KeyProviderError,
        MailboxServiceError,
        ValidationError,
        # The last net: a file the host does not let the service read or
        # write, e.g. the OAuth client secret.
        OSError,
    )


def message(exc: BaseException) -> str:
    found = getattr(exc, "message", None)
    return str(found or exc)


def say(text: str) -> None:
    """A message for the person at the terminal, on stderr. A script that
    reads the command's output never gets it."""
    print(text, file=sys.stderr)


def emit(text: str) -> None:
    """The command's result, on stdout, alone: what a script reads, such as
    a recovery key, a one-time password or the paths. The only way a
    secret leaves a command."""
    print(text)
