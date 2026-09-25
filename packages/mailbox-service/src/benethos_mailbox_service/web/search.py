"""The search a message list takes, by the names a query or a form uses.

The JSON API declares each parameter for its schema in ``api.deps``. The
names and the flags are the same there and here.
"""

from __future__ import annotations

from collections.abc import Mapping

from ..data.models import MessageFilter

# Query name -> filter field, for the text and date fields.
FIELDS = {
    "q": "text",
    "from": "sender",
    "to": "to",
    "subject": "subject",
    "after": "after",
    "before": "before",
}
# Set when present, whatever the value.
FLAGS = ("unread", "starred", "has_attachments")


def filter_from(values: Mapping[str, str]) -> MessageFilter | None:
    """The filter ``values`` ask for, None when they ask for nothing.
    Raises pydantic's ``ValidationError`` for a value that is no filter."""
    wanted: dict[str, object] = {
        field: values[name] for name, field in FIELDS.items() if values.get(name)
    }
    wanted.update({flag: True for flag in FLAGS if values.get(flag)})
    return MessageFilter(**wanted) if wanted else None
