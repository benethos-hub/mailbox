"""The REST client of the tools: the package benethos-mailbox-client,
its client for async code and the body of a message as the API takes
it. ``models`` names its records, ``errors`` its errors."""

from __future__ import annotations

from benethos_mailbox_client import MailboxClient, message_body, service_url

__all__ = ["MailboxClient", "message_body", "service_url"]
