"""The errors of the state file: ``StateFileError``, and
``StateConflictError`` for a row that collides with one stored. Each is
the error of the storage of mailbox-common as well, which raises them
for the agents."""

from __future__ import annotations

from benethos_mailbox_common.storage import errors as storage_errors

from .base import MailboxAgentError
from .config import ConfigError

__all__ = ["STATE_ERRORS", "StateConflictError", "StateFileError", "StateInUseError"]


class StateFileError(MailboxAgentError, storage_errors.StorageError):
    """The state file cannot be read or written: it is no SQLite file, it
    is damaged, or the disk is full. Nothing goes on without it."""

    code = "state_file"


class StateConflictError(StateFileError, storage_errors.ConflictError):
    """A row of the state file collides with one stored."""


class StateInUseError(ConfigError, storage_errors.StorageInUseError):
    """Another agent writes the state on the server already: one writer
    per database, as per state file."""


# What the storage of mailbox-common raises for the state file.
STATE_ERRORS = storage_errors.Errors(
    failed=StateFileError, conflict=StateConflictError, in_use=StateInUseError
)
