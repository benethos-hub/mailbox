"""POP3 data to the neutral model: ids, the one folder, cursors. Pure
functions, testable offline. What the message itself says comes from
``data.mail.convert``.

A message id holds the unique id the server gives the message (UIDL),
which stays the same for as long as the message is there.
"""

from __future__ import annotations

from typing import Any

from ....common import opaque
from ....errors import missing, missing_message
from ...mail import convert, parse
from ...models import Folder, FolderRole, Message, MessageSummary
from .. import rules

INBOX = "INBOX"
INBOX_NAME = "Inbox"


def folder_id() -> str:
    """The id of the one folder a POP3 mailbox has."""
    return opaque.encode("f_", [INBOX])


def inbox() -> Folder:
    return Folder(id=folder_id(), name=INBOX_NAME, role=FolderRole.INBOX)


def check_folder(value: str | None) -> None:
    """Nothing for the inbox or no folder, not found for any other id."""
    if value is not None and value != folder_id():
        raise missing("folder", value)


def message_id(uid: str) -> str:
    return opaque.encode("m_", [uid])


def unique_id(value: str) -> str:
    """The server's unique id behind a message id of this adapter."""
    try:
        parts = opaque.decode("m_", value)
    except ValueError:
        raise missing_message(value) from None
    if not isinstance(parts, list) or len(parts) != 1 or not isinstance(parts[0], str):
        raise missing_message(value)
    return parts[0]


def cursor(uid: str, position: int) -> str:
    """Where the next page starts: after the message ``uid``, which was at
    ``position`` counted from the newest, in case it is gone by then."""
    return opaque.encode("c_", [uid, position])


def parse_cursor(value: str) -> tuple[str, int]:
    try:
        parts = opaque.decode("c_", value)
    except ValueError:
        raise rules.invalid_cursor() from None
    if (
        not isinstance(parts, list)
        or len(parts) != 2
        or not isinstance(parts[0], str)
        or not isinstance(parts[1], int)
        or isinstance(parts[1], bool)
        or parts[1] < 0
    ):
        raise rules.invalid_cursor()
    return parts[0], parts[1]


def to_summary(msg: parse.ParsedMessage, uid: str) -> MessageSummary:
    return MessageSummary.model_validate(
        {**convert.summary_fields(msg), **_pop3_fields(uid)}
    )


def to_message(msg: parse.ParsedMessage, uid: str) -> Message:
    return Message.model_validate(
        {
            **convert.summary_fields(msg),
            **_pop3_fields(uid),
            **convert.message_fields(msg),
        }
    )


def _pop3_fields(uid: str) -> dict[str, Any]:
    """What only POP3 knows of a message: its id. It has no flags, so it
    is never unread or starred."""
    return {"id": message_id(uid), "folder_ids": [folder_id()]}
