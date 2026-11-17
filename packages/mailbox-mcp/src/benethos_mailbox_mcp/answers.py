"""What a tool answers as JSON, by name, field by field.

The MCP library makes a tool's output schema from these, so a client
knows the fields before it calls. A key without a value is left out
rather than sent as null, since the model reads every key: those are
``NotRequired``. ``render`` fills them.
"""

from __future__ import annotations

from typing import NotRequired

# TypedDict of typing_extensions, not of typing: pydantic reads the one
# of typing only from Python 3.12 on.
from typing_extensions import TypedDict

# A message in a list, without what the model does not need. "from" is
# a keyword of Python, so this one is written as a call.
Summary = TypedDict(
    "Summary",
    {
        "id": str,
        "account_id": str | None,
        "date": str | None,
        "from": str,
        "subject": str | None,
        "unread": bool,
        "starred": bool,
        "has_attachments": bool,
        "folders": list[str],
        "marks": NotRequired[list[str]],
        "keywords": NotRequired[list[str]],
        "thread_id": NotRequired[str],
        "snippet": NotRequired[str],
    },
)


class Page(TypedDict):
    """A page of summaries, with the accounts that did not answer."""

    messages: list[Summary]
    next_cursor: str | None
    note: str
    accounts_not_answering: NotRequired[list[str]]


class Change(TypedDict):
    """A change of the feed: its type and the message's ids."""

    type: str
    id: str
    account_id: str
    at: str


class Changes(TypedDict):
    """A page of the change feed, and the state to pass as since."""

    changes: list[Change]
    state: str
    more: bool
    note: str


class Failure(TypedDict):
    """A message a batch could not change, and why."""

    id: str
    error: str


class Outcome(TypedDict):
    """A batch: the ids done, and per failed id why not."""

    done: list[str]
    failed: list[Failure]


class Folder(TypedDict):
    """A folder of an account."""

    id: str
    name: str
    role: str | None
    parent: str | None
    unread: int | None
    total: int | None


class FolderName(TypedDict):
    """A folder just made, renamed or moved: its id from now on."""

    id: str
    name: str


class Account(TypedDict):
    """An account, what the caller may do there, and what it lacks."""

    id: str
    email: str
    name: str | None
    can: list[str]
    unsupported: NotRequired[list[str]]
    marks_written: NotRequired[list[str]]
    sending: NotRequired[list[str]]
    warning: NotRequired[str]
    status: NotRequired[str]
    attention: NotRequired[str]
    last_sync: NotRequired[str]


class Draft(TypedDict):
    """A draft in a list, or the one just written."""

    id: str
    date: str | None
    to: str
    subject: str | None


class Drafts(TypedDict):
    """A page of drafts."""

    drafts: list[Draft]
    next_cursor: str | None
    note: str


class Sent(TypedDict):
    """A mail sent: its Message-ID, the copy in Sent, who refused it."""

    sent: bool
    message_id_header: str
    sent_copy_id: NotRequired[str]
    refused: NotRequired[list[str]]
    original_marked: NotRequired[bool]
