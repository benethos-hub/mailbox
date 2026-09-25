"""What the mail pages offer, by the caller's rights on an account."""

from __future__ import annotations

from ...domain.access import Access


def mail_rights(caller: Access, account_id: str) -> dict[str, bool]:
    allowed = caller.operations_on(account_id)
    return {
        "write": "send_message" in allowed or "create_draft" in allowed,
        "send": "send_message" in allowed,
        "drafts": "list_drafts" in allowed,
        "change": "update_message" in allowed,
        "trash": "delete_message" in allowed,
        "purge": "delete_message_permanent" in allowed,
        "create_folder": "create_folder" in allowed,
        "update_folder": "update_folder" in allowed,
        "delete_folder": "delete_folder" in allowed,
        "batch": "batch_messages" in allowed,
    }
