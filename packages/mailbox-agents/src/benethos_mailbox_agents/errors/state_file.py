"""The errors of the state file: ``StateFileError``,
``StateConflictError`` for a row that collides with one stored,
``StateInUseError`` for a second writer on a server and
``StateUnavailableError`` for a server that is away. Each is the error
of the storage of mailbox-common as well, which raises them for the
agents."""

from __future__ import annotations

from benethos_mailbox_common.storage import errors as storage_errors

from .base import MailboxAgentError
from .config import ConfigError
from .unavailable import UnavailableError

__all__ = [
    "STATE_ERRORS",
    "StateConflictError",
    "StateFileError",
    "StateInUseError",
    "StateUnavailableError",
]


class StateFileError(MailboxAgentError, storage_errors.StorageError):
    """The state file cannot be read or written: it is no SQLite file, it
    is damaged, or the disk is full. Nothing goes on without it."""

    code = "state_file"


class StateConflictError(StateFileError, storage_errors.ConflictError):
    """A row of the state file collides with one stored."""


class StateInUseError(ConfigError, storage_errors.StorageInUseError):
    """Another agent writes the state on the server already: one writer
    per database, as per state file."""


class StateUnavailableError(UnavailableError, storage_errors.StorageUnavailableError):
    """The server of the state does not answer, for now. A normal
    condition, as for an upstream: the pass ends, the loop waits and tries
    again, nothing is decided without it. ``retry_after`` the seconds
    until the next attempt, ``cause`` what happened, for the log alone."""

    code = "state_unavailable"

    def __init__(self, retry_after: int, cause: str = "") -> None:
        super().__init__("the database of the state is not available at the moment")
        self.retry_after = retry_after
        self.cause = cause


# What the storage of mailbox-common raises for the state file.
STATE_ERRORS = storage_errors.Errors(
    failed=StateFileError,
    conflict=StateConflictError,
    in_use=StateInUseError,
    unavailable=StateUnavailableError,
)
