"""Each endpoint of the API the client knows, described once: the
request it makes and how its answer becomes a record of ``models``, one
module per resource of the API.

A function here sends nothing. It answers a ``Call``, which ``client``
and ``sync`` send. Nothing above this package spells out a path, a query
name or a field of the API.
"""

from __future__ import annotations

from .accounts import (
    create_account,
    delete_account,
    get_account,
    list_accounts,
    update_account,
    verify_account,
)
from .compose import message_body
from .discovery import discover_account, poll_device_oauth, start_device_oauth
from .drafts import create_draft, delete_draft, list_drafts, update_draft
from .folders import create_folder, delete_folder, list_folders, update_folder
from .generic import request
from .me import get_me
from .messages import (
    batch_messages,
    delete_message,
    get_attachment,
    get_message,
    get_message_raw,
    list_all_changes,
    list_all_messages,
    list_changes,
    list_messages,
    trash_messages,
    update_message,
    update_messages,
)
from .sending import send_draft, send_message
from .webhooks import renew_webhook_secret, update_webhook

__all__ = [
    "discover_account",
    "poll_device_oauth",
    "start_device_oauth",
    "create_account",
    "delete_account",
    "get_account",
    "list_accounts",
    "update_account",
    "verify_account",
    "create_draft",
    "create_folder",
    "delete_draft",
    "delete_folder",
    "delete_message",
    "get_attachment",
    "get_me",
    "get_message",
    "get_message_raw",
    "list_all_changes",
    "list_all_messages",
    "update_message",
    "batch_messages",
    "list_changes",
    "list_drafts",
    "list_folders",
    "list_messages",
    "message_body",
    "renew_webhook_secret",
    "request",
    "send_draft",
    "send_message",
    "trash_messages",
    "update_draft",
    "update_folder",
    "update_messages",
    "update_webhook",
]
