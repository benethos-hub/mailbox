"""The POP3 adapter's messages, against a fake server: listing and
reading, permanent deletion and what the sync reads."""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from benethos_mailbox_service.data.models import MessageFilter
from benethos_mailbox_service.data.protocols.pop3 import Pop3Session
from benethos_mailbox_service.data.providers.pop3 import Pop3Provider, mappers
from benethos_mailbox_service.data.providers.pop3 import provider as pop3_module
from benethos_mailbox_service.errors import (
    BadRequestError,
    MessageNotFoundError,
    NotFoundError,
    NotSupportedError,
    ProviderError,
)

from ...imap_fake import make_message
from ...pop3_fake import FakePop3Server
from .test_pop3 import (
    INBOX,
    SETTINGS,
    filled_server,
    pop3_protocol_server,
    provider,
    subjects,
)


@pytest.fixture
def server() -> FakePop3Server:
    return filled_server()


async def test_newest_first_with_a_cursor(server: FakePop3Server) -> None:
    adapter = provider(server)
    first = await adapter.list_messages(None, limit=2, cursor=None)
    assert subjects(first.items) == ["Mail 5", "Mail 4"]
    assert first.items[0].folder_ids == [INBOX]
    assert not first.items[0].unread and not first.items[0].starred
    second = await adapter.list_messages(INBOX, limit=2, cursor=first.next_cursor)
    assert subjects(second.items) == ["Mail 3", "Mail 2"]
    third = await adapter.list_messages(INBOX, limit=2, cursor=second.next_cursor)
    assert subjects(third.items) == ["Mail 1"] and third.next_cursor is None


async def test_a_cursor_holds_when_messages_arrive_or_leave(
    server: FakePop3Server,
) -> None:
    adapter = provider(server)
    first = await adapter.list_messages(None, limit=2, cursor=None)
    server.add("uid-6", make_message("Mail 6"))
    following = await adapter.list_messages(None, limit=2, cursor=first.next_cursor)
    assert subjects(following.items) == ["Mail 3", "Mail 2"]


async def test_a_cursor_whose_message_is_gone_goes_on_from_its_place(
    server: FakePop3Server,
) -> None:
    adapter = provider(server)
    first = await adapter.list_messages(None, limit=2, cursor=None)
    del server.messages["uid-4"]
    following = await adapter.list_messages(None, limit=2, cursor=first.next_cursor)
    assert subjects(following.items) == ["Mail 3", "Mail 2"]


async def test_lists_read_headers_only(server: FakePop3Server) -> None:
    await provider(server).list_messages(None, limit=2, cursor=None)
    names = {call[0] for call in server.calls}
    assert "top" in names and "retr" not in names


async def test_without_top_the_whole_message_gives_the_headers(
    server: FakePop3Server,
) -> None:
    server.top = False
    server.capabilities = ["UIDL", "USER"]
    page = await provider(server).list_messages(None, limit=1, cursor=None)
    assert subjects(page.items) == ["Mail 5"]


@pytest.mark.parametrize("cursor", ["junk", mappers.message_id("uid-1")])
async def test_an_invalid_cursor(server: FakePop3Server, cursor: str) -> None:
    with pytest.raises(BadRequestError, match="invalid cursor"):
        await provider(server).list_messages(None, limit=2, cursor=cursor)


async def test_another_folder_is_not_found(server: FakePop3Server) -> None:
    with pytest.raises(NotFoundError, match="folder"):
        await provider(server).list_messages("f_other", limit=2, cursor=None)


async def test_a_search_is_not_supported(server: FakePop3Server) -> None:
    adapter = provider(server)
    with pytest.raises(NotSupportedError, match="searched"):
        await adapter.list_messages(
            None, limit=2, cursor=None, search=MessageFilter(unread=True)
        )
    # An empty filter narrows nothing.
    page = await adapter.list_messages(
        None, limit=2, cursor=None, search=MessageFilter()
    )
    assert len(page.items) == 2


async def test_a_message_its_attachment_and_its_source(
    server: FakePop3Server,
) -> None:
    server.add(
        "uid-9",
        make_message(
            "With files", attachments=[("a.txt", "text/plain", b"attached text")]
        ),
    )
    adapter = provider(server)
    message_id = mappers.message_id("uid-9")
    message = await adapter.get_message(message_id)
    assert message.id == message_id and message.subject == "With files"
    assert message.text_body and message.text_body.strip() == "Hello"
    [attachment] = message.attachments
    content = await adapter.get_attachment(message_id, attachment.id)
    assert content.data == b"attached text"
    assert b"Subject: With files" in await adapter.get_raw(message_id)


@pytest.mark.parametrize("message_id", ["junk", mappers.message_id("uid-404")])
async def test_a_missing_message(server: FakePop3Server, message_id: str) -> None:
    with pytest.raises(MessageNotFoundError):
        await provider(server).get_message(message_id)


async def test_a_message_too_large_is_refused(server: FakePop3Server) -> None:
    adapter = Pop3Provider(
        SETTINGS,
        lambda f: SecretStr("secret"),
        session_factory=lambda s: Pop3Session(
            s, connection_factory=server, max_bytes=100
        ),
    )
    with pytest.raises(ProviderError, match="larger than 100 bytes"):
        await adapter.get_raw(mappers.message_id("uid-1"))


async def test_every_step_sees_the_mailbox_as_it_is_now(
    server: FakePop3Server,
) -> None:
    """A POP3 session sees the mailbox as at its login: each step logs in
    afresh and quits at once, so the server is never held locked."""
    adapter = provider(server)
    await adapter.list_messages(None, limit=1, cursor=None)
    server.add("uid-6", make_message("Mail 6"))
    page = await adapter.list_messages(None, limit=1, cursor=None)
    assert subjects(page.items) == ["Mail 6"]
    assert server.connections == 2
    assert [c[0] for c in server.calls].count("quit") == 2


# --- changing messages ------------------------------------------------------------


async def test_no_trash(server: FakePop3Server) -> None:
    with pytest.raises(NotSupportedError, match="no trash"):
        await provider(server).delete_messages(
            [mappers.message_id("uid-1")], permanent=False
        )
    assert "uid-1" in server.messages


async def test_deleting_for_good(server: FakePop3Server) -> None:
    one, two = mappers.message_id("uid-1"), mappers.message_id("uid-2")
    results = await provider(server).delete_messages(
        [one, two, mappers.message_id("uid-404"), "junk"], permanent=True
    )
    assert results[one] is None and results[two] is None
    assert isinstance(results[mappers.message_id("uid-404")], MessageNotFoundError)
    assert isinstance(results["junk"], MessageNotFoundError)
    assert list(server.messages) == ["uid-3", "uid-4", "uid-5"]


async def test_a_quit_the_server_does_not_confirm_keeps_the_messages(
    server: FakePop3Server,
) -> None:
    server.quit_refusal = b"-ERR could not remove"
    with pytest.raises(ProviderError, match="did not finish"):
        await provider(server).delete_messages(
            [mappers.message_id("uid-1")], permanent=True
        )
    assert "uid-1" in server.messages


def test_a_retried_delete_counts_a_message_gone_as_deleted(
    server: FakePop3Server,
) -> None:
    """The first try may have ended its session with QUIT before the
    connection dropped: on the retry the message is gone, as wanted."""
    session = Pop3Session(pop3_protocol_server(), connection_factory=server)
    session.login("me", "secret")
    wanted = {mappers.message_id("uid-404"): "uid-404"}
    assert pop3_module._delete(session, wanted, retried=True) == {
        mappers.message_id("uid-404"): None
    }
    first = pop3_module._delete(session, wanted, retried=False)
    assert isinstance(first[mappers.message_id("uid-404")], MessageNotFoundError)


# --- for the sync -----------------------------------------------------------------


async def test_the_state_changes_when_mail_arrives_or_leaves(
    server: FakePop3Server,
) -> None:
    adapter = provider(server)
    before = await adapter.folder_states()
    assert list(before) == [INBOX]
    assert await adapter.folder_states() == before
    server.add("uid-6", make_message("Mail 6"))
    arrived = await adapter.folder_states()
    del server.messages["uid-1"]
    left = await adapter.folder_states()
    assert len({before[INBOX], arrived[INBOX], left[INBOX]}) == 3


async def test_contents_and_headers(
    server: FakePop3Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pop3_module, "HEADER_BATCH", 2)
    adapter = provider(server)
    contents = await adapter.folder_contents(INBOX)
    assert contents == [mappers.message_id(f"uid-{n}") for n in range(1, 6)]
    server.calls.clear()
    headers = await adapter.message_headers([*contents, "junk"])
    assert set(headers) == set(contents)
    assert all(h and h.startswith("<") for h in headers.values())
    # Three sessions of at most two messages each.
    assert [c[0] for c in server.calls].count("quit") == 3


async def test_no_flags_to_compare(server: FakePop3Server) -> None:
    adapter = provider(server)
    assert await adapter.flag_changes(INBOX, "x", [mappers.message_id("uid-1")]) == []
