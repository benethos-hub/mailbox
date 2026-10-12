"""The ``microsoft`` adapter against a Graph mailbox in memory: a message
read from its MIME, and a mail sent as a draft whose copy keeps its id."""

from __future__ import annotations

from email import message_from_bytes
from email.message import EmailMessage
from email.policy import default

import httpx
import pytest

from benethos_mailbox_service.errors import (
    BadRequestError,
    NotFoundError,
    ProviderUnavailableError,
)

from ...graph_fake import FakeGraph
from .test_microsoft import adapter


@pytest.fixture
def graph() -> FakeGraph:
    return FakeGraph()


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
    assert message.unread and message.starred and message.keywords == ["work"]
    assert message.text_body == "Hi\n" and message.html_body == "<p>Hi</p>\n"
    assert message.in_reply_to == "<original@example.com>"
    assert [a.filename for a in message.attachments] == ["offer.pdf"]
    assert message.has_attachments
    content = await provider.get_attachment(message_id, message.attachments[0].id)
    assert content.data == b"%PDF"
    assert (await provider.get_raw(message_id)).startswith(b"Subject:")


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

    async def stuck(message_id: str, trash: str | None = None) -> None:
        raise ProviderUnavailableError("graph is busy")

    monkeypatch.setattr(provider, "_delete_for_good", stuck)
    graph.send_answer = httpx.Response(
        400, json={"error": {"code": "ErrorInvalidRecipients", "message": "no"}}
    )
    with pytest.raises(BadRequestError, match="it stays as the draft AAMk"):
        await provider.send(SENT, "me@example.org", ["bob@example.org"])
    [draft] = graph.messages.values()
    assert draft["isDraft"]
