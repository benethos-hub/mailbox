"""What a message to send or to keep as a draft must be: the caller's
rights, the size of its attachments, its recipients. And whether a draft
sent back is the one stored."""

from __future__ import annotations

from ...common.sizes import MIB, megabytes
from ...data.mail import convert
from ...data.models import Address, DraftMessage, MessageReference, Recipient
from ...errors import BadRequestError
from ..rights import Access

# What one message may carry.
MAX_RECIPIENTS = 100
MAX_ATTACHMENT_BYTES = 25 * MIB


def require(
    access: Access, operation: str, account_id: str, message: DraftMessage
) -> None:
    """The operation's right and, with a reference, the right to read: a
    reply quotes the original and a forward passes it on. Whoever may only
    send or write drafts must not get at mail this way. Then the size."""
    access.require(operation, account_id)
    if message.reference is not None:
        access.require("get_message", account_id)
    if sum(len(a.data) for a in message.attachments) > MAX_ATTACHMENT_BYTES:
        raise BadRequestError(
            f"the attachments exceed {megabytes(MAX_ATTACHMENT_BYTES)}"
        )


def limited(recipients: list[str]) -> list[str]:
    """No more recipients than the service carries. Checked once composed:
    a reply takes its recipients from the original."""
    if len(recipients) > MAX_RECIPIENTS:
        raise BadRequestError(f"at most {MAX_RECIPIENTS} recipients")
    return recipients


def addressed(recipients: list[str]) -> list[str]:
    """A message to send needs at least one recipient. A reply finds them
    in the original, a forward or a plain message brings its own."""
    if not recipients:
        raise BadRequestError("a message needs at least one recipient")
    return limited(recipients)


def same(
    stored: convert.StoredDraft, draft: DraftMessage, keep: list[str] | None
) -> bool:
    """Whether ``draft`` is the draft as it is stored: the same addresses,
    subject, bodies and original, every attachment kept and none added.
    Whitespace counts as one space, as a form sends a text back."""
    if draft.attachments or sorted(keep or []) != sorted(stored.attachment_ids):
        return False
    if draft.reference is not None and draft.reference.quote:
        return False  # composing adds the quote again

    def people(values: list[Recipient] | list[Address]) -> list[tuple[str, str]]:
        return [(v.email.lower(), (v.name or "").strip()) for v in values]

    def words(value: str | None) -> str:
        return " ".join((value or "").split())

    def original(reference: MessageReference | None) -> tuple[str, ...] | None:
        if reference is None:
            return None
        return (reference.message_id, reference.action, reference.forward_as)

    return (
        people(draft.to) == people(stored.to)
        and people(draft.cc) == people(stored.cc)
        and people(draft.bcc) == people(stored.bcc)
        and people(draft.reply_to) == people(stored.reply_to)
        and words(draft.subject) == words(stored.subject)
        and (draft.text is None or words(draft.text) == words(stored.text))
        and words(draft.html) == words(stored.html)
        and original(draft.reference) == original(stored.reference)
    )
