"""The ``microsoft`` adapter against a Graph mailbox in memory: a message
read from its MIME, and a mail sent as a draft whose copy keeps its id."""

from __future__ import annotations

from datetime import UTC, datetime
from email import message_from_bytes
from email.message import EmailMessage
from email.policy import default
from typing import Any

import httpx
import pytest

from benethos_mailbox_service.data.models import MessageUpdate
from benethos_mailbox_service.data.providers.microsoft import (
    messages as microsoft_messages,
)
from benethos_mailbox_service.errors import (
    BadRequestError,
    MessageNotFoundError,
    NotFoundError,
    ProviderError,
    ProviderUnavailableError,
)

from ...graph_fake import FakeGraph
from ...microsoft_adapter import adapter
from ...provider_ops import delete, update

# --- reading --------------------------------------------------------------------------


def mime(text: str | None, html: str | None = None) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = "Hello"
    message["Message-ID"] = "<reply@example.com>"
    message["In-Reply-To"] = "<original@example.com>"
    if text is not None:
        message.set_content(text)
    if html is not None:
        message.add_alternative(html, subtype="html")
    return message


async def test_a_message(graph: FakeGraph) -> None:
    """Graph's fields for what it keeps, the MIME for the rest."""
    raw = mime("Hi", "<p>Hi</p>")
    raw.add_attachment(b"%PDF", "application", "pdf", filename="offer.pdf")
    message_id = graph.add_message(
        raw=raw.as_bytes(),
        hasAttachments=True,
        flag={"flagStatus": "flagged"},
        categories=["Work"],
    )
    provider = adapter(graph)
    message = await provider.get_message(message_id)
    assert message.sender is not None and message.sender.email == "alice@example.com"
    assert message.unread and message.starred and message.keywords == ["Work"]
    assert message.text_body == "Hi\n" and message.html_body == "<p>Hi</p>\n"
    assert message.in_reply_to == "<original@example.com>"
    assert [a.filename for a in message.attachments] == ["offer.pdf"]
    assert message.has_attachments
    content = await provider.get_attachment(message_id, message.attachments[0].id)
    assert content.data == b"%PDF"
    assert (await provider.get_raw(message_id)).startswith(b"Subject:")


async def test_date_is_when_it_was_sent_and_received_when_it_came(
    graph: FakeGraph,
) -> None:
    message_id = graph.add_message(
        sentDateTime="2026-09-01T09:59:00Z", receivedDateTime="2026-09-01T10:00:00Z"
    )
    message = await adapter(graph).get_message(message_id)
    assert message.date == datetime(2026, 9, 1, 9, 59, tzinfo=UTC)
    assert message.received == datetime(2026, 9, 1, 10, tzinfo=UTC)


async def test_a_plain_text_mail_has_no_html(graph: FakeGraph) -> None:
    """Graph's own body would be Exchange's HTML."""
    message_id = graph.add_message(raw=mime("Just text").as_bytes())
    message = await adapter(graph).get_message(message_id)
    assert message.text_body == "Just text\n" and message.html_body is None


async def test_inline_images_alone_can_be_fetched(graph: FakeGraph) -> None:
    """Graph says such a mail has no attachments, and lists none."""
    raw = mime(None, '<p><img src="cid:logo@example.com"></p>')
    [html] = raw.iter_parts() if raw.is_multipart() else [raw]
    html.add_related(b"\x89PNG", "image", "png", cid="<logo@example.com>")
    message_id = graph.add_message(raw=raw.as_bytes(), hasAttachments=False)
    provider = adapter(graph)
    message = await provider.get_message(message_id)
    [image] = message.attachments
    assert image.inline and image.content_type == "image/png"
    assert not message.has_attachments
    content = await provider.get_attachment(message_id, image.id)
    assert content.data == b"\x89PNG"


async def test_an_attachment_of_another_id_is_not_found(graph: FakeGraph) -> None:
    message_id = graph.add_message()
    with pytest.raises(NotFoundError):
        await adapter(graph).get_attachment(message_id, "AAMkatt1=")


async def test_an_id_graph_cannot_read_is_a_message_not_found(
    graph: FakeGraph,
) -> None:
    """Graph answers 400 for it, the other providers 404."""
    provider = adapter(graph)
    with pytest.raises(MessageNotFoundError):
        await provider.get_message("not an id")
    with pytest.raises(MessageNotFoundError):
        await provider.get_raw("not an id")
    with pytest.raises(MessageNotFoundError):
        await update(provider, "not an id", MessageUpdate(add_keywords=["work"]))
    for permanent in (False, True):
        with pytest.raises(MessageNotFoundError):
            await delete(provider, "not an id", permanent)


# --- sending ------------------------------------------------------------------------


SENT = b"From: me@example.org\r\nTo: bob@example.org\r\nSubject: Hi\r\n\r\nHello\r\n"


async def test_send_puts_hidden_recipients_in_bcc(graph: FakeGraph) -> None:
    await adapter(graph).send(
        SENT, "me@example.org", ["bob@example.org", "carol@example.org"]
    )
    [sent] = graph.sent
    parsed = message_from_bytes(sent, policy=default)
    assert parsed["To"] == "bob@example.org"
    assert parsed["Bcc"] == "carol@example.org"
    assert parsed.get_content().strip() == "Hello"


async def test_send_answers_the_copy_in_sent_items(graph: FakeGraph) -> None:
    """Sent as a draft, whose id the copy keeps."""
    result = await adapter(graph).send(SENT, "me@example.org", ["bob@example.org"])
    copy = result.sent_copy
    assert copy is not None and "$draft" not in copy.keywords
    assert copy.folder_ids == [graph.well_known["sentitems"]]
    stored = graph.messages[copy.id]
    assert stored["parentFolderId"] == graph.well_known["sentitems"]
    assert not stored["isDraft"]


async def test_a_draft_not_sent_goes_again(
    graph: FakeGraph, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Graph refuses the send: no draft stays behind. Where it cannot go,
    the error names it."""
    provider = adapter(graph)
    graph.send_answer = httpx.Response(
        400, json={"error": {"code": "ErrorInvalidRecipients", "message": "no"}}
    )
    with pytest.raises(BadRequestError, match="no"):
        await provider.send(SENT, "me@example.org", ["bob@example.org"])
    assert graph.messages == {} and graph.sent == []

    async def stuck(graph: Any, message_id: str, trash: str | None = None) -> None:
        raise ProviderUnavailableError("graph is busy")

    monkeypatch.setattr(microsoft_messages, "delete_for_good", stuck)
    graph.send_answer = httpx.Response(
        400, json={"error": {"code": "ErrorInvalidRecipients", "message": "no"}}
    )
    with pytest.raises(BadRequestError, match="it stays as the draft AAMk"):
        await provider.send(SENT, "me@example.org", ["bob@example.org"])
    [draft] = graph.messages.values()
    assert draft["isDraft"]


# --- large mail -----------------------------------------------------------------------

SESSION = 3_000_000


def large() -> bytes:
    """A mail beyond one Graph request: a file below the size of an upload
    session and one above it."""
    mail = mime("Files")
    mail.add_attachment(b"s" * (SESSION - 1), "text", "plain", filename="small.txt")
    mail.add_attachment(b"L" * 4_000_000, "application", "zip", filename="large.zip")
    return mail.as_bytes()


async def test_a_large_mail_sends_its_files_one_by_one(graph: FakeGraph) -> None:
    """No request goes beyond Graph's limit: the fake would answer 413."""
    result = await adapter(graph).send(large(), "me@example.org", ["bob@example.org"])
    [sent] = graph.sent
    files = {
        part.get_filename(): part.get_payload(decode=True)
        for part in message_from_bytes(sent, policy=default).iter_attachments()
    }
    assert files == {"small.txt": b"s" * (SESSION - 1), "large.zip": b"L" * 4_000_000}
    puts = [r for r in graph.requests if r.method == "PUT"]
    assert len(puts) == 2 and graph.sessions == {}
    assert result.sent_copy is not None


async def test_a_large_draft_keeps_its_files(graph: FakeGraph) -> None:
    provider = adapter(graph)
    saved = await provider.save_draft(large(), None)
    message = await provider.get_message(saved.id)
    assert [a.filename for a in message.attachments] == ["small.txt", "large.zip"]


async def test_a_file_that_cannot_go_takes_the_draft_back(
    graph: FakeGraph, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refused(request: httpx.Request, session: str) -> httpx.Response:
        return httpx.Response(
            500, json={"error": {"code": "ErrorInternalServerError", "message": "x"}}
        )

    monkeypatch.setattr(graph, "_upload", refused)
    with pytest.raises(ProviderError, match="x"):
        await adapter(graph).send(large(), "me@example.org", ["bob@example.org"])
    assert graph.messages == {} and graph.sent == []


async def test_a_small_mail_is_one_request(graph: FakeGraph) -> None:
    await adapter(graph).save_draft(mime("Short").as_bytes(), None)
    assert not [r for r in graph.requests if "attachments" in r.url.path]
