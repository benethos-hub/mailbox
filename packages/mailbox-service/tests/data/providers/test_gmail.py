"""The ``gmail`` adapter against a Gmail mailbox in memory: reading,
changing, folders, drafts and sending."""

from __future__ import annotations

from datetime import date
from email import message_from_bytes
from email.policy import default

import httpx
import pytest
from pydantic import SecretStr

from benethos_mailbox_service.data.models import (
    FolderRole,
    MessageFilter,
    MessageSummary,
    MessageUpdate,
)
from benethos_mailbox_service.data.protocols.http import ApiClient
from benethos_mailbox_service.data.providers import capabilities_of
from benethos_mailbox_service.data.providers.base import Capability
from benethos_mailbox_service.data.providers.gmail import GmailProvider, mappers
from benethos_mailbox_service.data.providers.gmail.shapes import Label
from benethos_mailbox_service.errors import (
    BadRequestError,
    ConflictError,
    MessageNotFoundError,
    NotFoundError,
    NotSupportedError,
)

from ...gmail_fake import TOKEN, FakeGmail


class Tokens:
    def __init__(self, *values: str) -> None:
        self.values = list(values)
        self.rejected = 0
        self.forgotten = 0

    async def access_token(self) -> SecretStr:
        return SecretStr(self.values[0])

    def reject(self) -> None:
        self.rejected += 1
        if len(self.values) > 1:
            self.values.pop(0)

    def forget_refusal(self) -> None:
        self.forgotten += 1


@pytest.fixture
def gmail() -> FakeGmail:
    return FakeGmail()


def adapter(gmail: FakeGmail, tokens: Tokens | None = None) -> GmailProvider:
    return GmailProvider(
        tokens or Tokens(TOKEN), ApiClient(transport=httpx.MockTransport(gmail))
    )


# --- mappers --------------------------------------------------------------------------


def test_labels_with_a_role_and_those_of_a_person_are_folders() -> None:
    labels = [
        Label(id="INBOX", name="INBOX", type="system"),
        Label(id="UNREAD", name="UNREAD", type="system"),
        Label(id="CATEGORY_SOCIAL", name="CATEGORY_SOCIAL", type="system"),
        Label(id="SPAM", name="SPAM", type="system"),
        Label(id="Label_1", name="Work", type="user"),
        Label(id="Label_2", name="Work/2026", type="user"),
        Label(id="Label_3", name="Old/Gone", type="user"),
    ]
    found = {f.id: f for f in mappers.folders(labels)}
    assert set(found) == {"ALL_MAIL", "INBOX", "SPAM", "Label_1", "Label_2", "Label_3"}
    assert found["ALL_MAIL"].role is FolderRole.ALL
    assert found["SPAM"].role is FolderRole.JUNK and found["SPAM"].name == "Spam"
    assert found["Label_2"].name == "2026" and found["Label_2"].parent_id == "Label_1"
    # Its parent is no label: it stays at the top.
    assert found["Label_3"].name == "Gone" and found["Label_3"].parent_id is None


def test_a_message_in_the_trash_is_in_the_trash_alone() -> None:
    known = {"INBOX", "TRASH", "Label_1"}
    assert mappers.folder_ids(["INBOX", "UNREAD", "Label_1"], known) == [
        "INBOX",
        "Label_1",
        "ALL_MAIL",
    ]
    assert mappers.folder_ids(["INBOX", "TRASH"], known) == ["TRASH"]
    assert mappers.in_folder("ALL_MAIL", {"Label_1"})
    assert not mappers.in_folder("INBOX", {"INBOX", "SPAM"})


def test_a_filter_in_gmails_search_syntax() -> None:
    query = mappers.query(
        MessageFilter(
            text='say "hi"',
            sender="alice",
            subject="Invoice",
            after=date(2026, 9, 1),
            before=date(2026, 9, 2),
            unread=True,
            starred=False,
            has_attachments=True,
        )
    )
    assert query == (
        '"say hi" from:"alice" subject:"Invoice" after:1788220799 '
        "before:1788307200 is:unread -is:starred has:attachment"
    )
    assert mappers.query(None) is None
    assert mappers.query(MessageFilter()) is None


def test_a_cursor_belongs_to_its_list() -> None:
    inbox = mappers.scope("INBOX", None)
    cursor = mappers.cursor(inbox, "17")
    assert mappers.page_token(cursor, inbox) == "17"
    with pytest.raises(BadRequestError):
        mappers.page_token(cursor, mappers.scope("SENT", None))
    with pytest.raises(BadRequestError):
        mappers.page_token("made-up", inbox)


# --- reading --------------------------------------------------------------------------


def test_the_adapter_offers_what_gmail_can() -> None:
    found = capabilities_of(GmailProvider(Tokens(TOKEN)))
    assert {
        Capability.LABELS,
        Capability.DELTA,
        Capability.DRAFTS,
        Capability.FOLDERS,
        Capability.STABLE_IDS,
        Capability.SEND,
    } <= found
    assert Capability.PUSH not in found


async def test_folders_with_their_counts(gmail: FakeGmail) -> None:
    work = gmail.new_label("Work")
    gmail.add_message()
    gmail.add_message(labels=("INBOX", work))
    found = {f.id: f for f in await adapter(gmail).list_folders()}
    assert found["INBOX"].total == 2 and found["INBOX"].unread == 1
    assert found[work].name == "Work" and found[work].total == 1
    assert "UNREAD" not in found and "CHAT" not in found


async def test_a_folder_newest_first_page_by_page(gmail: FakeGmail) -> None:
    first, second, third = (gmail.add_message(subject=f"m{n}") for n in range(3))
    provider = adapter(gmail)
    page = await provider.list_messages("INBOX", limit=2, cursor=None)
    assert [m.id for m in page.items] == [third, second]
    assert page.next_cursor is not None
    rest = await provider.list_messages("INBOX", limit=2, cursor=page.next_cursor)
    assert [m.id for m in rest.items] == [first] and rest.next_cursor is None
    with pytest.raises(BadRequestError):
        await provider.list_messages("SENT", limit=2, cursor=page.next_cursor)


async def test_a_summary_from_the_headers(gmail: FakeGmail) -> None:
    gmail.add_message(subject="Grüße", sender="Jörg <j@example.com>")
    [summary] = (
        await adapter(gmail).list_messages("INBOX", limit=5, cursor=None)
    ).items
    assert summary.subject == "Grüße"
    assert summary.sender is not None and summary.sender.name == "Jörg"
    assert summary.unread and not summary.starred
    assert summary.folder_ids == ["INBOX", "ALL_MAIL"]
    assert summary.snippet == "Hi & there"
    assert summary.thread_id and summary.date is not None


async def test_all_mail_leaves_out_the_trash_and_no_folder_does_not(
    gmail: FakeGmail,
) -> None:
    kept = gmail.add_message()
    trashed = gmail.add_message(labels=("TRASH",))
    provider = adapter(gmail)
    all_mail = await provider.list_messages("ALL_MAIL", limit=10, cursor=None)
    assert [m.id for m in all_mail.items] == [kept]
    everything = await provider.list_messages(None, limit=10, cursor=None)
    assert {m.id for m in everything.items} == {kept, trashed}
    trash = await provider.list_messages("TRASH", limit=10, cursor=None)
    assert [m.id for m in trash.items] == [trashed]


async def test_a_search_goes_to_gmail(gmail: FakeGmail) -> None:
    gmail.add_message(subject="Invoice")
    read = gmail.add_message(labels=("INBOX",), subject="Invoice")
    page = await adapter(gmail).list_messages(
        "INBOX",
        limit=10,
        cursor=None,
        search=MessageFilter(text="invoice", unread=False),
    )
    assert [m.id for m in page.items] == [read]
    [request] = [r for r in gmail.requests if r.url.path.endswith("/messages")]
    assert request.url.params["q"] == '"invoice" -is:unread'


async def test_an_unknown_folder_is_not_found(gmail: FakeGmail) -> None:
    with pytest.raises(NotFoundError):
        await adapter(gmail).list_messages("Label_404", limit=5, cursor=None)


async def test_a_whole_message(gmail: FakeGmail) -> None:
    message_id = gmail.add_message(body="The body")
    found = await adapter(gmail).get_message(message_id)
    assert found.text_body is not None and "The body" in found.text_body
    assert found.message_id_header == "<m@example.com>"
    assert found.folder_ids == ["INBOX", "ALL_MAIL"] and found.unread
    raw = await adapter(gmail).get_raw(message_id)
    assert message_from_bytes(raw, policy=default)["Subject"] == "Hello"


async def test_a_message_that_is_not_there(gmail: FakeGmail) -> None:
    provider = adapter(gmail)
    with pytest.raises(MessageNotFoundError):
        await provider.get_message("00000000000000ff")
    before = len(gmail.requests)
    with pytest.raises(MessageNotFoundError):
        await provider.get_message("../labels")
    assert len(gmail.requests) == before


# --- changing -------------------------------------------------------------------------


async def test_flags_are_labels(gmail: FakeGmail) -> None:
    message_id = gmail.add_message()
    result = await adapter(gmail).update_messages(
        [message_id], MessageUpdate(unread=False, starred=True)
    )
    summary = result[message_id]
    assert isinstance(summary, MessageSummary)
    assert not summary.unread and summary.starred
    assert set(gmail.messages[message_id]["labelIds"]) == {"INBOX", "STARRED"}


async def test_a_move_sets_the_folders_exactly(gmail: FakeGmail) -> None:
    work = gmail.new_label("Work")
    message_id = gmail.add_message(labels=("INBOX", "UNREAD", "IMPORTANT"))
    provider = adapter(gmail)
    moved = await provider.update_messages(
        [message_id], MessageUpdate(folder_ids=[work])
    )
    assert isinstance(moved[message_id], MessageSummary)
    labels = set(gmail.messages[message_id]["labelIds"])
    assert labels == {work, "UNREAD", "IMPORTANT"}
    # Archived: in "All Mail" alone.
    await provider.update_messages([message_id], MessageUpdate(folder_ids=["ALL_MAIL"]))
    assert set(gmail.messages[message_id]["labelIds"]) == {"UNREAD", "IMPORTANT"}


async def test_moves_gmail_does_itself_are_refused(gmail: FakeGmail) -> None:
    message_id = gmail.add_message()
    provider = adapter(gmail)
    sent = await provider.update_messages(
        [message_id], MessageUpdate(folder_ids=["SENT"])
    )
    assert isinstance(sent[message_id], BadRequestError)
    unknown = await provider.update_messages(
        [message_id], MessageUpdate(folder_ids=["Label_9"])
    )
    assert isinstance(unknown[message_id], NotFoundError)
    tagged = await provider.update_messages(
        [message_id], MessageUpdate(keywords=["work"])
    )
    assert isinstance(tagged[message_id], NotSupportedError)
    gone = await provider.update_messages(
        ["00000000000000ff"], MessageUpdate(unread=True)
    )
    assert isinstance(gone["00000000000000ff"], MessageNotFoundError)


async def test_a_delete_goes_to_the_trash_then_for_good(gmail: FakeGmail) -> None:
    message_id = gmail.add_message()
    provider = adapter(gmail)
    trashed = (await provider.delete_messages([message_id], permanent=False))[
        message_id
    ]
    assert isinstance(trashed, MessageSummary) and trashed.folder_ids == ["TRASH"]
    again = await provider.delete_messages([message_id], permanent=False)
    assert isinstance(again[message_id], ConflictError)
    assert await provider.delete_messages([message_id], permanent=True) == {
        message_id: None
    }
    assert message_id not in gmail.messages
    missing = await provider.delete_messages([message_id], permanent=True)
    assert isinstance(missing[message_id], MessageNotFoundError)


# --- folders --------------------------------------------------------------------------


async def test_a_folder_in_a_folder(gmail: FakeGmail) -> None:
    provider = adapter(gmail)
    work = await provider.create_folder("Work", None)
    year = await provider.create_folder("2026", work.id)
    assert year.parent_id == work.id
    assert gmail.labels[year.id]["name"] == "Work/2026"
    with pytest.raises(BadRequestError):
        await provider.create_folder("a/b", None)
    with pytest.raises(BadRequestError):
        await provider.create_folder("x", "INBOX")


async def test_a_rename_takes_the_folders_inside_along(gmail: FakeGmail) -> None:
    work = gmail.new_label("Work")
    year = gmail.new_label("Work/2026")
    other = gmail.new_label("Workshop")
    provider = adapter(gmail)
    renamed = await provider.update_folder(work, "Job", None)
    assert renamed.name == "Job"
    assert gmail.labels[year]["name"] == "Job/2026"
    assert gmail.labels[other]["name"] == "Workshop"
    with pytest.raises(BadRequestError):
        await provider.update_folder(work, "Job", year)
    with pytest.raises(BadRequestError):
        await provider.update_folder("INBOX", "In", None)
    await provider.delete_folder(year)
    assert year not in gmail.labels
    with pytest.raises(NotFoundError):
        await provider.delete_folder(year)


# --- drafts and sending ---------------------------------------------------------------


async def test_a_draft_replaced_gets_a_new_id(gmail: FakeGmail) -> None:
    provider = adapter(gmail)
    first = await provider.save_draft(b"Subject: One\r\n\r\nfirst", None)
    assert first.folder_ids == ["DRAFT", "ALL_MAIL"]
    second = await provider.save_draft(b"Subject: Two\r\n\r\nsecond", first.id)
    assert second.id != first.id and second.subject == "Two"
    assert first.id not in gmail.messages
    assert b"second" in await provider.get_draft(second.id)
    listed = await provider.list_drafts(limit=10, cursor=None)
    assert [d.id for d in listed.items] == [second.id]
    await provider.delete_draft(second.id)
    assert gmail.drafts == {}
    with pytest.raises(NotFoundError):
        await provider.delete_draft(second.id)


async def test_only_a_draft_is_a_draft(gmail: FakeGmail) -> None:
    message_id = gmail.add_message()
    provider = adapter(gmail)
    with pytest.raises(NotFoundError, match="draft"):
        await provider.get_draft(message_id)
    with pytest.raises(NotFoundError, match="draft"):
        await provider.save_draft(b"Subject: x\r\n\r\n", message_id)


async def test_a_send_names_the_hidden_recipients(gmail: FakeGmail) -> None:
    raw = b"From: me@gmail.com\r\nTo: a@example.com\r\nSubject: Hi\r\n\r\nHello"
    sent = await adapter(gmail).send(
        raw, "me@gmail.com", ["a@example.com", "b@example.com"]
    )
    [out] = gmail.sent
    assert message_from_bytes(out, policy=default)["Bcc"] == "b@example.com"
    assert sent.sent_copy is not None and sent.sent_copy.folder_ids == [
        "SENT",
        "ALL_MAIL",
    ]
