"""The records the REST client answers with, as the client package
defines them. A message, a summary in a page and a draft are not
records: they stay the JSON of the API, since ``render`` shows them
whole and nothing else reads them."""

from __future__ import annotations

from benethos_mailbox_client import (
    Attachment,
    Changes,
    Folder,
    Me,
    MeAccount,
    Outcome,
    Page,
    Recipient,
    Sending,
    Sent,
)

__all__ = [
    "Attachment",
    "Changes",
    "Folder",
    "Me",
    "MeAccount",
    "Outcome",
    "Page",
    "Recipient",
    "Sending",
    "Sent",
]
