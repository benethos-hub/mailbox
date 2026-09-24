"""One message at a time through the providers' batch operations, raising
the per-message error the way a single operation would."""

from __future__ import annotations

from benethos_mailbox_api.data.models import MessageSummary, MessageUpdate
from benethos_mailbox_api.data.providers import MailProvider
from benethos_mailbox_api.errors import MailboxApiError


async def update(
    provider: MailProvider, message_id: str, changes: MessageUpdate
) -> MessageSummary:
    outcome = (await provider.update_messages([message_id], changes))[message_id]
    if isinstance(outcome, MailboxApiError):
        raise outcome
    return outcome


async def delete(
    provider: MailProvider, message_id: str, permanent: bool
) -> MessageSummary | None:
    outcome = (await provider.delete_messages([message_id], permanent))[message_id]
    if isinstance(outcome, MailboxApiError):
        raise outcome
    return outcome
