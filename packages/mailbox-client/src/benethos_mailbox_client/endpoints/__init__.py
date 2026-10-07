"""Each endpoint of the API the client knows, described once: the
request it makes and how its answer becomes a record of ``models``, one
module per resource of the API.

A function here sends nothing. It answers a ``Call``, which ``client``
and ``sync`` send. Nothing above this package spells out a path, a query
name or a field of the API.
"""

from __future__ import annotations

from .accounts import me
from .compose import message_body
from .drafts import create_draft, delete_draft, list_drafts, update_draft
from .folders import create_folder, list_folders
from .generic import request
from .messages import (
    delete_message,
    get_attachment,
    get_message,
    list_changes,
    list_messages,
    trash_messages,
    update_messages,
)
from .sending import send_draft, send_message

__all__ = [
    "create_draft",
    "create_folder",
    "delete_draft",
    "delete_message",
    "get_attachment",
    "get_message",
    "list_changes",
    "list_drafts",
    "list_folders",
    "list_messages",
    "me",
    "message_body",
    "request",
    "send_draft",
    "send_message",
    "trash_messages",
    "update_draft",
    "update_messages",
]
