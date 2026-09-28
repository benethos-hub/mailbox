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
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, TypeVar

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
N = TypeVar("N", int, float)


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
    """A port from the settings: a whole number from 1 to 65535."""
    return _number(
        settings, key, default, int, lambda p: 1 <= p <= 65535, "a port from 1 to 65535"
    )


def rate_of(settings: ProviderSettings, key: str, default: float) -> float:
    """A rate per minute from the settings: a number above 0."""
    return _number(
        settings, key, default, float, lambda r: 0 < r < math.inf, "a number above 0"
    )


def _number(
    settings: ProviderSettings,
    key: str,
    default: N,
    read: Callable[[Any], N],
    valid: Callable[[N], bool],
    must_be: str,
) -> N:
    """The number under ``key``, ``default`` when it is not set. A value
    ``read`` cannot take, a truth value or one not ``valid`` is refused."""
    value = settings.get(key)
    if value is None or value == "":
        return default
    try:
        number = None if isinstance(value, bool) else read(value)
    except (TypeError, ValueError):
        number = None
    if number is None or not valid(number):
        raise BadRequestError(f"settings.{key} must be {must_be}")
    return number


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
