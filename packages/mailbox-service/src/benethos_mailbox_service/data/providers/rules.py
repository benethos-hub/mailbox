"""What every adapter answers the same way.

The contract in ``base`` says what an adapter does. This says how the
adapters agree on the situations each of them meets: a folder with a role
the account lacks, a cursor the caller made up, a move to several folders,
and the outcome per id of a batch. An adapter uses these instead of
raising an error of its own choosing, so callers see one behaviour
whatever the provider.
"""

from __future__ import annotations

import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

from ...errors import (
    BadRequestError,
    ConflictError,
    MailboxServiceError,
    ProviderAuthError,
    ProviderUnavailableError,
)
from ..models import Folder, FolderRole, MessageUpdate
from .base import Capability

R = TypeVar("R")


def no_folder(role: FolderRole) -> ConflictError:
    """The account has no folder with this role: the operation cannot
    happen until it does."""
    if role is FolderRole.TRASH:
        return ConflictError(
            "the account has no trash folder: a message can only be deleted for good"
        )
    return ConflictError(f"the account has no {role} folder")


def resting(reason: str, wait: float) -> ProviderUnavailableError:
    """The server is left alone for ``wait`` seconds more, for ``reason``."""
    return ProviderUnavailableError(f"{reason}: next attempt in {math.ceil(wait)}s")


def in_trash_already() -> ConflictError:
    return ConflictError(
        "the message is in the trash already: only a delete for good removes it"
    )


def invalid_cursor() -> BadRequestError:
    """A cursor the adapter did not hand out, or one from another list."""
    return BadRequestError("invalid cursor")


@dataclass(frozen=True)
class After:
    """Where the next page starts: after the item ``last``, which was at
    ``position``, in case it is gone by then."""

    last: str
    position: int


def role_folder(folders: list[Folder], role: FolderRole) -> Folder | None:
    return next((f for f in folders if f.role is role), None)


def require_role_folder(folders: list[Folder], role: FolderRole) -> Folder:
    """The folder with ``role``, ``no_folder`` when the account has none."""
    folder = role_folder(folders, role)
    if folder is None:
        raise no_folder(role)
    return folder


def move_target(
    changes: MessageUpdate, capabilities: frozenset[Capability]
) -> str | None:
    """The folder ``changes`` move a message to, or None to stay. Several
    folders at once need ``LABELS``."""
    if changes.folder_ids is None:
        return None
    if len(set(changes.folder_ids)) != 1 and Capability.LABELS not in capabilities:
        raise BadRequestError("a message of this account is in exactly one folder")
    return changes.folder_ids[0]


# Failures that stop a batch as a whole: the connection or the login, not
# one message.
FATAL = (ProviderAuthError, ProviderUnavailableError)


async def per_id(
    ids: list[str], one: Callable[[str], Awaitable[R]]
) -> dict[str, R | MailboxServiceError]:
    """``one`` for each id, with the outcome or the failure per id. A
    failed login or connection stops everything and raises, as the
    contract of ``update_messages`` and ``delete_messages`` says."""
    results: dict[str, R | MailboxServiceError] = {}
    for message_id in ids:
        try:
            results[message_id] = await one(message_id)
        except FATAL:
            raise
        except MailboxServiceError as exc:
            results[message_id] = exc
    return results
