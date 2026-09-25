"""What every adapter answers the same way.

The contract in ``base`` says what an adapter does. This says how the
adapters agree on the situations each of them meets: a folder with a role
the account lacks, a cursor the caller made up, a move to several folders,
and the outcome per id of a batch. An adapter uses these instead of
raising an error of its own choosing, so callers see one behaviour
whatever the provider.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import TypeVar

from ...errors import (
    BadRequestError,
    ConflictError,
    MailboxServiceError,
    ProviderAuthError,
    ProviderUnavailableError,
)
from ..models import Folder, FolderRole, MessageUpdate
from .base import Capability, ProviderSettings

R = TypeVar("R")


def no_folder(role: FolderRole) -> ConflictError:
    """The account has no folder with this role: the operation cannot
    happen until it does."""
    if role is FolderRole.TRASH:
        return ConflictError(
            "the account has no trash folder: delete with permanent=true"
        )
    return ConflictError(f"the account has no {role} folder")


def in_trash_already() -> ConflictError:
    return ConflictError(
        "the message is in the trash already: delete with permanent=true"
    )


def invalid_cursor() -> BadRequestError:
    """A cursor the adapter did not hand out, or one from another list."""
    return BadRequestError("invalid cursor")


def role_folder(folders: list[Folder], role: FolderRole) -> Folder | None:
    return next((f for f in folders if f.role is role), None)


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


def encrypted(settings: ProviderSettings, key: str, protocol: str) -> str:
    """The ``security`` setting under ``key``: ``tls`` (the default) or
    ``starttls``. Nothing else: a connection without encryption is refused."""
    security = str(settings.get(key, "tls"))
    if security not in ("tls", "starttls"):
        raise BadRequestError(
            f"settings.{key} must be 'tls' or 'starttls': "
            f"{protocol} without encryption is not supported"
        )
    return security


def port_of(settings: ProviderSettings, key: str, default: int) -> int:
    return int(settings.get(key) or default)


def hosts_in(settings: Mapping[str, object]) -> list[tuple[str, str, int]]:
    """Every server the settings name, as (key, host, port): ``host`` with
    ``port``, ``smtp_host`` with ``smtp_port``, and any other ``*_host``.
    Port 0 where none is set."""
    found = []
    for key, value in settings.items():
        if not (key == "host" or key.endswith("_host")):
            continue
        if not isinstance(value, str) or not value:
            continue
        port = settings.get(key[: -len("host")] + "port")
        found.append((key, value, port if isinstance(port, int) else 0))
    return found


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
        except (ProviderAuthError, ProviderUnavailableError):
            raise
        except MailboxServiceError as exc:
            results[message_id] = exc
    return results
