"""What the Gmail API sends, as shapes. Every field but an id may be
missing: a message comes in the format asked for, a list without its
items when it is empty."""

from __future__ import annotations

from typing import Annotated

from pydantic import NonNegativeInt

from ...protocols import wire

Text = Annotated[str | None, wire.OrNone]
Count = Annotated[NonNegativeInt | None, wire.OrNone]
Ids = Annotated[list[str], wire.OrNone]


class Label(wire.CamelShape):
    """A label, a folder of the API. ``type`` is ``system`` or ``user``."""

    id: str
    name: Text = None
    type: Text = None
    messages_total: Count = None
    messages_unread: Count = None


class Labels(wire.CamelShape):
    labels: list[Label] = []


class Header(wire.Shape):
    name: str
    value: str = ""


class Part(wire.CamelShape):
    """The top part of a message, with its headers in the order sent."""

    mime_type: Text = None
    headers: list[Header] = []


class GmailMessage(wire.CamelShape):
    """A message in the format ``minimal``, ``metadata`` or ``raw``.
    ``internal_date``: when Gmail received it, in milliseconds since 1970,
    written as a string. ``raw``: the source in URL-safe base64."""

    id: str
    thread_id: Text = None
    label_ids: Ids = []
    snippet: Text = None
    history_id: Text = None
    internal_date: Text = None
    payload: Annotated[Part | None, wire.OrNone] = None
    raw: Text = None


class Messages(wire.CamelShape):
    """A page of message ids, newest first."""

    messages: list[GmailMessage] = []
    next_page_token: Text = None


class Draft(wire.CamelShape):
    """A draft: an id of its own, and the message that holds it now."""

    id: str
    message: Annotated[GmailMessage | None, wire.OrNone] = None


class Drafts(wire.CamelShape):
    drafts: list[Draft] = []
    next_page_token: Text = None


class Profile(wire.CamelShape):
    email_address: Text = None
    history_id: Text = None


class Added(wire.CamelShape):
    """A message that arrived, or that was deleted for good."""

    message: GmailMessage


class LabelChange(wire.CamelShape):
    """Labels added to a message or taken off it. ``message`` holds the
    labels it has now."""

    message: GmailMessage
    label_ids: Ids = []


class History(wire.CamelShape):
    """One change of the mailbox."""

    id: Text = None
    messages_added: list[Added] = []
    messages_deleted: list[Added] = []
    labels_added: list[LabelChange] = []
    labels_removed: list[LabelChange] = []


class Histories(wire.CamelShape):
    """A page of changes since a history id. ``history_id``: the mailbox's
    history id now, where the next question starts."""

    history: list[History] = []
    next_page_token: Text = None
    history_id: Text = None


class Reason(wire.Shape):
    reason: Text = None


class ErrorDetail(wire.Shape):
    code: Annotated[int | None, wire.OrNone] = None
    message: Text = None
    status: Text = None
    errors: Annotated[list[Reason], wire.OrNone] = []


class Failure(wire.Shape):
    error: Annotated[ErrorDetail | None, wire.OrNone] = None
