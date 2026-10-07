"""What an account's adapter can do beyond reading, asked before it is
asked to do it.

An adapter implements only the protocols of ``data.providers`` it can.
Where one is missing, the domain answers ``501 not_supported`` here, the
same for every kind of account.
"""

from __future__ import annotations

from ...data.providers import Deletes, Deltas, Drafts, Reads, Sends, Watches, Writes
from ...errors import NotSupportedError


def writes(adapter: Reads) -> Writes:
    if isinstance(adapter, Writes):
        return adapter
    raise NotSupportedError(
        "this account keeps no folders, read state, stars or keywords to change"
    )


def deletes(adapter: Reads) -> Deletes:
    if isinstance(adapter, Deletes):
        return adapter
    raise NotSupportedError("this account cannot delete messages")


def drafts(adapter: Reads) -> Drafts:
    if isinstance(adapter, Drafts):
        return adapter
    raise NotSupportedError("this account keeps no drafts")


def sends(adapter: Reads) -> Sends:
    if isinstance(adapter, Sends):
        return adapter
    raise NotSupportedError("this account cannot send")


def watches(adapter: Reads) -> Watches:
    if isinstance(adapter, Watches):
        return adapter
    raise NotSupportedError("this account reports no change by itself: it is polled")


def deltas(adapter: Reads) -> Deltas:
    if isinstance(adapter, Deltas):
        return adapter
    raise NotSupportedError(
        "this account tells no changes since a point: its folders are compared"
    )
