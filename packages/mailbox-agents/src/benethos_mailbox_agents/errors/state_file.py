"""The errors of the state file: ``StateFileError``, and
``StateConflictError`` for a row that collides with one stored. Each is
the error of the storage of mailbox-common as well, which raises them
for the agents."""

from __future__ import annotations

from benethos_mailbox_common.storage import errors as storage_errors

from .base import MailboxAgentError

__all__ = ["STATE_ERRORS", "StateConflictError", "StateFileError"]


class StateFileError(MailboxAgentError, storage_errors.StorageError):
    """The state file cannot be read or written: it is no SQLite file, it
    is damaged, or the disk is full. Nothing goes on without it."""

    code = "state_file"


class StateConflictError(StateFileError, storage_errors.ConflictError):
    """A row of the state file collides with one stored."""


# What the storage of mailbox-common raises for the state file.
STATE_ERRORS = storage_errors.Errors(failed=StateFileError, conflict=StateConflictError)
