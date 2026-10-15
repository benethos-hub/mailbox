"""What the mail pages offer an account: the operations the API answers
for it (UNIFORM U1), the caller's rights and what the account can do
together. Which parts of a change of messages it offers, and what a
message shows, follow the account's capabilities. The templates ask
``can`` alone, never a capability or a kind of account (U2)."""

from __future__ import annotations

from ...data.models import Account, Capability


def mail_rights(account: Account) -> dict[str, bool]:
    """``account`` as the caller sees it, with its ``operations``."""
    offered = set(account.operations)
    able = set(account.capabilities)
    changes = "update_message" in offered
    read_state = changes and Capability.READ_STATE in able
    star = changes and Capability.STARS in able
    keywords = changes and Capability.KEYWORDS in able
    move = changes and Capability.MOVE in able
    return {
        "write": "send_message" in offered or "create_draft" in offered,
        "send": "send_message" in offered,
        "drafts": "list_drafts" in offered,
        # What a message shows: its read state and stars, its keywords.
        "shows_flags": Capability.READ_STATE in able,
        "shows_keywords": Capability.KEYWORDS in able,
        "read_state": read_state,
        "star": star,
        "keywords": keywords,
        "move": move,
        "change": read_state or star or keywords or move,
        "trash": "delete_message" in offered,
        "purge": "delete_message_permanent" in offered,
        "create_folder": "create_folder" in offered,
        "update_folder": "update_folder" in offered,
        "delete_folder": "delete_folder" in offered,
        "search": Capability.SEARCH in able,
        "threads": "list_threads" in offered,
        "thread": "get_thread" in offered,
    }
