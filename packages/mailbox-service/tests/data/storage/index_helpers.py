"""Entries of the message index, for its tests."""

from __future__ import annotations

from benethos_mailbox_service.data.storage import (
    IndexEntry,
)

ACC = "acc_1"


def entry(n: int, folder: str = "f_inbox", header: str | None = None) -> IndexEntry:
    return IndexEntry(id=f"msg_{n}", native_id=f"n{n}", folder_id=folder, header=header)
