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

from benethos_mailbox_common.values import canonical, secret

from ...common import opaque
from ...errors import (
    BadRequestError,
    ConflictError,
    MailboxServiceError,
    NotSupportedError,
    ProviderAuthError,
    ProviderError,
    ProviderUnavailableError,
)
from ..models import Folder, FolderRole, MessageFilter, MessageUpdate

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


def no_folder_left() -> BadRequestError:
    """A change that would take a message out of its last folder."""
    return BadRequestError("a message stays in one folder at least")


def invalid_cursor() -> BadRequestError:
    """A cursor the adapter did not hand out, or one from another list."""
    return BadRequestError("invalid cursor")


def cursor_scope(folder_id: str | None, search: MessageFilter | None) -> str:
    """What a cursor belongs to: the folder and the search, shortened.
    Two that collide cost a page of the other search, never another
    account's mail."""
    what = canonical.canonical(
        [folder_id, (search or MessageFilter()).model_dump(mode="json")]
    )
    return secret.digest(what)[:16]


def bound_cursor(prefix: str, scope: str, value: str) -> str:
    """A provider's next page, bound to the list it belongs to."""
    return opaque.encode(prefix, [scope, value])


def cursor_value(prefix: str, cursor: str, scope: str) -> str:
    """The provider's next page of a cursor of this list. Another list's
    cursor, or one made up, is refused."""
    parts = opaque.fields(prefix, cursor, str, str)
    if parts is None or parts[0] != scope or not parts[1]:
        raise invalid_cursor()
    return str(parts[1])


@dataclass(frozen=True)
class After:
    """Where the next page starts: after the item ``last``, which was at
    ``position``, in case it is gone by then."""

    last: str
    position: int


def role_folder(folders: list[Folder], role: FolderRole) -> Folder | None:
    return next((f for f in folders if f.role is role), None)


async def replaced(
    new_id: str,
    drop_old: Callable[[], Awaitable[None]],
    drop_new: Callable[[], Awaitable[None]],
) -> None:
    """A draft stored anew drops the one it replaces. Where that fails,
    the new one goes again, so the replacing changed nothing. Where even
    that fails, the error names the new one beside the old."""
    try:
        await drop_old()
    except MailboxServiceError as exc:
        try:
            await drop_new()
        except MailboxServiceError:
            raise kept_both(exc, new_id) from exc
        raise


def kept_both(failure: MailboxServiceError, new_id: str) -> ProviderError:
    """A replaced draft that stayed, beside the new one."""
    return ProviderError(
        f"{failure.message}: the draft {new_id} replacing it stays beside it"
    )


def require_role_folder(folders: list[Folder], role: FolderRole) -> Folder:
    """The folder with ``role``, ``no_folder`` when the account has none."""
    folder = role_folder(folders, role)
    if folder is None:
        raise no_folder(role)
    return folder


def move_target(changes: MessageUpdate, labels: bool) -> str | None:
    """The folder ``changes`` move a message to, or None to stay. Several
    folders at once need ``labels``, and so does adding or removing one.
    The domain checks that first."""
    if not labels and (
        changes.adds_or_removes_folders
        or (changes.folder_ids is not None and len(set(changes.folder_ids)) != 1)
    ):
        raise NotSupportedError(
            "a message of this account is in exactly one folder: "
            "move it with one folder in folder_ids"
        )
    if changes.folder_ids is None:
        return None
    return changes.folder_ids[0]


# Failures that stop a batch as a whole: the connection or the login, not
# one message. Once some messages are done, they answer for the rest.
FATAL = (ProviderAuthError, ProviderUnavailableError)


async def per_id(
    ids: list[str], one: Callable[[str], Awaitable[R]]
) -> dict[str, R | MailboxServiceError]:
    """``one`` for each id, with the outcome or the failure per id. A
    failed login or connection stops everything and raises, as the
    contract of ``update_messages`` and ``delete_messages`` says. Once
    some ids are done, it is the failure of the rest instead, so the
    answer names what was done."""
    results: dict[str, R | MailboxServiceError] = {}
    for n, message_id in enumerate(ids):
        try:
            results[message_id] = await one(message_id)
        except FATAL as exc:
            if not results:
                raise
            return {**results, **dict.fromkeys(ids[n:], exc)}
        except MailboxServiceError as exc:
            results[message_id] = exc
    return results
