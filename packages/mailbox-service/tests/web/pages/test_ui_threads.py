"""Conversations in the UI: a folder listed by them, a conversation's
page, and the card of the others on a message's page. Through a JMAP
account, which keeps its threads."""

from __future__ import annotations

import pytest

from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.data.models import Grant

from ...imap_fake import make_message
from ...jmap_fake import FakeJmap
from ...ui_helpers import signed_in


@pytest.fixture
def conversation(jmap_server: FakeJmap) -> tuple[str, str]:
    """Hello in the inbox and its answer in Sent, one thread."""
    first = jmap_server.add_email(make_message("Hello"), thread="T1")
    second = jmap_server.add_email(
        make_message("Re: Hello"), mailbox="sent", thread="T1"
    )
    return first, second


def test_a_folder_listed_by_conversations(
    jmap_services: Services, jmap_account_id: str, conversation: tuple[str, str]
) -> None:
    client = signed_in(jmap_services)
    url = f"/ui/accounts/{jmap_account_id}/mail?folder=inbox"
    messages = client.get(url).text
    assert (
        ">Conversations</a>" in messages and 'aria-current="page">Messages' in messages
    )
    assert "<th>Folder</th>" not in messages
    listed = client.get(f"{url}&view=threads")
    assert listed.status_code == 200, listed.text
    page = listed.text
    assert 'aria-current="page">Conversations' in page
    assert f'/ui/accounts/{jmap_account_id}/threads/T1?folder=inbox"' in page
    assert "2 messages" in page
    # The folders of its messages, by name.
    assert '<span class="tag">Inbox</span>' in page
    assert '<span class="tag">Sent</span>' in page
    # No search and no batch for conversations.
    assert 'name="q"' not in page and 'id="batch"' not in page


def test_the_page_of_a_conversation(
    jmap_services: Services, jmap_account_id: str, conversation: tuple[str, str]
) -> None:
    client = signed_in(jmap_services)
    found = client.get(f"/ui/accounts/{jmap_account_id}/threads/T1?folder=inbox")
    assert found.status_code == 200, found.text
    page = found.text
    first, second = conversation
    assert page.index(f"/mail/{first}") < page.index(f"/mail/{second}")
    assert "<th>Folder</th>" in page and "Sent" in page
    # The way back is the folder it was opened from.
    assert f"/ui/accounts/{jmap_account_id}/mail?folder=inbox" in page
    assert client.get(f"/ui/accounts/{jmap_account_id}/threads/T9").status_code == 404


def test_a_message_names_the_others_of_its_conversation(
    jmap_services: Services,
    jmap_account_id: str,
    jmap_server: FakeJmap,
    conversation: tuple[str, str],
) -> None:
    client = signed_in(jmap_services)
    first, second = conversation
    page = client.get(f"/ui/accounts/{jmap_account_id}/mail/{first}").text
    card = page[page.index("In this conversation") :]
    assert f"/mail/{second}" in card and f"/mail/{first}" not in card
    assert f"/ui/accounts/{jmap_account_id}/threads/T1" in card
    # Mail 1 of the server is alone in its thread: no card.
    alone = next(iter(jmap_server.emails))
    page = client.get(f"/ui/accounts/{jmap_account_id}/mail/{alone}").text
    assert "Mail 1" in page and "In this conversation" not in page


def test_without_the_rights_no_conversations_show(
    jmap_services: Services, jmap_account_id: str, conversation: tuple[str, str]
) -> None:
    reading = Grant(
        accounts=[jmap_account_id],
        allow=["list_folders", "list_messages", "get_message"],
    )
    client = signed_in(jmap_services, reading)
    first, _ = conversation
    folder = client.get(f"/ui/accounts/{jmap_account_id}/mail?folder=inbox").text
    assert "Conversations" not in folder
    # Asked for anyway, the folder lists its messages.
    listed = client.get(
        f"/ui/accounts/{jmap_account_id}/mail?folder=inbox&view=threads"
    ).text
    assert "Conversations" not in listed and "Hello" in listed
    assert (
        "In this conversation"
        not in client.get(f"/ui/accounts/{jmap_account_id}/mail/{first}").text
    )
    assert client.get(f"/ui/accounts/{jmap_account_id}/threads/T1").status_code == 403
