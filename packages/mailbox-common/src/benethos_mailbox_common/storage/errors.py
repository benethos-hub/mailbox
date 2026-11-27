"""The errors of the storage, and which of them a program has raised.

The group raises what its caller names in ``Errors``: a program whose
errors carry a meaning of their own, such as a status of HTTP, hands in
its classes, each a subclass of the one here, so a ``except`` of the
program catches what the storage raises. Without, the classes here.
No text of an error holds a value of a row.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


class StorageError(Exception):
    """The storage failed: busy, damaged or unreadable."""


class ConflictError(Exception):
    """A record collides with what is stored: a key taken, or a reference
    to a record that is gone."""


class NotFoundError(Exception):
    """A record that is not there."""

    @classmethod
    def of(cls, what: str, name: str) -> NotFoundError:
        """``<what> <name> not found``."""
        return cls(f"{what} {name} not found")


class StorageInUseError(StorageError):
    """Another program holds the database."""


class SchemaNotEmptyError(StorageError):
    """A schema on a server that holds tables, where a restore or a move
    goes into an empty one only."""


class StorageUnavailableError(StorageError):
    """The database cannot be reached, for now: ``retry_after`` the
    seconds until the next attempt, ``cause`` what happened, for the log
    alone."""

    retry_after: int = 1
    cause: str = ""

    @classmethod
    def after(cls, retry_after: int, cause: str = "") -> StorageUnavailableError:
        """Away for ``retry_after`` seconds more, for ``cause``."""
        found = cls("the database is not available at the moment")
        found.retry_after = retry_after
        found.cause = cause
        return found


@dataclass(frozen=True, slots=True)
class Errors:
    """What the storage raises: for a failure, a conflict with a stored
    record, a record not there (what it is and its id), a database another
    program holds, a schema that is not empty, and a database away (the
    seconds until the next attempt and the cause)."""

    failed: Callable[[str], StorageError] = StorageError
    conflict: Callable[[str], ConflictError] = ConflictError
    missing: Callable[[str, str], NotFoundError] = NotFoundError.of
    in_use: Callable[[str], StorageInUseError] = StorageInUseError
    not_empty: Callable[[str], SchemaNotEmptyError] = SchemaNotEmptyError
    unavailable: Callable[[int, str], StorageUnavailableError] = (
        StorageUnavailableError.after
    )


# The classes of this group.
OWN = Errors()
