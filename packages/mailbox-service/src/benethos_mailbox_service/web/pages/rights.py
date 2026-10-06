"""What the mail pages offer, by the caller's rights on an account and by
what the account can do: a POP3 account has no flags, folders, search or
drafts, so their actions are not offered there."""

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
    flag = "update_message" in allowed and Capability.FLAGS in able
    move = "update_message" in allowed and folders
    return {
        "write": "send_message" in allowed or ("create_draft" in allowed and drafts),
        "send": "send_message" in allowed,
        "drafts": "list_drafts" in allowed and drafts,
        "flag": flag,
        "move": move,
        "change": flag or move,
        "trash": "delete_message" in allowed and folders,
        "purge": "delete_message_permanent" in allowed,
        "create_folder": "create_folder" in allowed and folders,
        "update_folder": "update_folder" in allowed and folders,
        "delete_folder": "delete_folder" in allowed and folders,
        "search": Capability.SEARCH in able,
    }
