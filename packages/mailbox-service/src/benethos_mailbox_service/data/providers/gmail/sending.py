"""Sending and drafts as Gmail's raw messages.

``messages.send`` sends and keeps the copy in Sent itself. A draft has an
id of its own at Gmail, but the API names it by the id of the message
that holds it: that message has the label ``DRAFT``. Gmail gives a
draft a new message when it is replaced, so a replaced draft gets a
new id.
"""

from __future__ import annotations

from ....common.opaque import to_base64
from ....errors import MailboxServiceError, NotFoundError, missing
from ...mail import compose
from ...models import MessageSummary, Page, SentMessage
from . import mappers, reading
from .api import GmailApi, id_
from .messages import list_messages
from .shapes import Draft, Drafts, GmailMessage


async def send(
    api: GmailApi, raw: bytes, sender: str, recipients: list[str]
) -> SentMessage:
    """Gmail takes the recipients from the headers. Those the headers do
    not name are the Bcc ones: they go in a Bcc header, which Gmail takes
    out before delivery and keeps in the copy."""
    body = {"raw": to_base64(compose.with_bcc(raw, recipients))}
    sent = await api.read(GmailMessage, "POST", "/messages/send", json_body=body)
    # Sent: from here on nothing may fail, or a client would send again.
    try:
        copy = await reading.summary(api, sent.id)
    except MailboxServiceError as exc:
        return SentMessage(copy_error=exc.message)
    return SentMessage(sent_copy=copy)


async def list_drafts(
    api: GmailApi, limit: int, cursor: str | None
) -> Page[MessageSummary]:
    return await list_messages(api, mappers.DRAFT, limit, cursor, None)


async def save_draft(api: GmailApi, raw: bytes, replaces: str | None) -> MessageSummary:
    body = {"message": {"raw": to_base64(raw)}}
    if replaces is None:
        draft = await api.read(Draft, "POST", "/drafts", json_body=body)
    else:
        draft_id = await _draft_id(api, replaces)
        draft = await api.read(Draft, "PUT", f"/drafts/{id_(draft_id)}", json_body=body)
    stored = await reading.summary(api, draft.message.id) if draft.message else None
    if stored is None:
        raise NotFoundError("the draft was stored but cannot be found again")
    return stored


async def get_draft(api: GmailApi, draft_id: str) -> bytes:
    found = await _draft_message(api, draft_id)
    return reading.source(found)


async def delete_draft(api: GmailApi, draft_id: str) -> None:
    gmail_id = await _draft_id(api, draft_id)
    try:
        await api.call("DELETE", f"/drafts/{id_(gmail_id)}")
    except NotFoundError:
        raise missing("draft", draft_id) from None


async def _draft_message(api: GmailApi, draft_id: str) -> GmailMessage:
    """The message of a draft with its source. Only drafts: any other id
    is not found, so the draft operations reach no other mail."""
    if not reading.is_id(draft_id):
        raise missing("draft", draft_id)
    try:
        found = await reading.with_source(api, draft_id)
    except NotFoundError:
        raise missing("draft", draft_id) from None
    if mappers.DRAFT not in found.label_ids:
        raise missing("draft", draft_id)
    return found


async def _draft_id(api: GmailApi, draft_id: str) -> str:
    """Gmail's id of the draft whose message is ``draft_id``."""
    if reading.is_id(draft_id):
        token: str | None = None
        while True:
            params = [("maxResults", str(reading.PAGE_SIZE))]
            if token:
                params.append(("pageToken", token))
            page = await api.read(Drafts, "GET", "/drafts", params=params)
            for draft in page.drafts:
                if draft.message is not None and draft.message.id == draft_id:
                    return draft.id
            token = page.next_page_token
            if not token:
                break
    raise missing("draft", draft_id)
