"""What the mail pages offer, by the caller's rights on an account and by
what the account can do: a POP3 account keeps no read state, folders,
drafts or threads, so their actions are not offered there."""

from __future__ import annotations

from collections.abc import Iterable

from ...data.models import Capability
from ...domain.rights import Access


def mail_rights(
    caller: Access, account_id: str, capabilities: Iterable[Capability]
) -> dict[str, bool]:
    allowed = caller.operations_on(account_id)
    able = set(capabilities)
    drafts = Capability.DRAFTS in able
    folders = Capability.FOLDERS in able
    sends = "send_message" in allowed and Capability.SEND in able
    changes = "update_message" in allowed
    read_state = changes and Capability.READ_STATE in able
    star = changes and Capability.STARS in able
    keywords = changes and Capability.KEYWORDS in able
    move = changes and Capability.MOVE in able
    return {
        "write": sends or ("create_draft" in allowed and drafts),
        "send": sends,
        "drafts": "list_drafts" in allowed and drafts,
        # What a message shows: its read state and stars, its keywords.
        "shows_flags": Capability.READ_STATE in able,
        "shows_keywords": Capability.KEYWORDS in able,
        "read_state": read_state,
        "star": star,
        "keywords": keywords,
        "move": move,
        "change": read_state or star or keywords or move,
        "trash": "delete_message" in allowed and Capability.TRASH in able,
        "purge": "delete_message_permanent" in allowed and Capability.PURGE in able,
        "create_folder": "create_folder" in allowed and folders,
        "update_folder": "update_folder" in allowed and folders,
        "delete_folder": "delete_folder" in allowed and folders,
        "search": Capability.SEARCH in able,
        "threads": "list_threads" in allowed and Capability.THREADS in able,
        "thread": "get_thread" in allowed and Capability.THREADS in able,
    }
