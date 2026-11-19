"""A list that gives messages their ids, at the same time as a sync pass
or a change of ours, and before a pass saw what another program did: the
feed tells no id the index does not hold, the list answers, and a
message keeps its id."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import pytest

from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.data.models import MessageUpdate
from benethos_mailbox_service.data.providers import ThreadHeaders
from benethos_mailbox_service.data.providers.imap import mappers
from benethos_mailbox_service.errors import NotFoundError, ProviderUnavailableError

from ...conftest import ADMIN
from ...imap_fake import FakeMailBox, make_message
from ..sync_helpers import ids_by_subject, recorded

ARCHIVE = mappers.folder_id("Archive")


def before_the_first_headers(
    services: Services,
    account: str,
    monkeypatch: pytest.MonkeyPatch,
    meanwhile: Callable[[], Awaitable[None]],
) -> None:
    """Run ``meanwhile`` once, when the adapter is first asked for
    headers and before it answers: the place a list and a pass wait."""
    adapter = services.adapters.get(account)
    real = adapter.message_headers
    asked: list[list[str]] = []

    async def headers(natives: list[str]) -> dict[str, ThreadHeaders]:
        asked.append(natives)
        if len(asked) == 1:
            await meanwhile()
        return await real(natives)

    monkeypatch.setattr(adapter, "message_headers", headers)


async def archive_by_subject(services: Services, account: str) -> dict[str, str]:
    page = await services.mailbox.list_messages(
        ADMIN, account, folder_id=ARCHIVE, limit=50, cursor=None
    )
    return {m.subject or "": m.id for m in page.items}


# --- a list and a pass at the same time ---------------------------------------------


async def test_a_pass_tells_no_id_of_its_own_for_a_mail_a_list_named(
    imap_services: Services,
    imap_account_id: str,
    imap_server: FakeMailBox,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    services, account = imap_services, imap_account_id
    await services.sync.sync_account(account)
    told_before = len(recorded(services, account))
    imap_server.add("INBOX", 9, make_message("New"))
    listed: dict[str, str] = {}

    async def a_caller_lists_the_inbox() -> None:
        listed.update(await ids_by_subject(services, account))

    # The pass reads the new mail's header. Meanwhile the list names it.
    before_the_first_headers(services, account, monkeypatch, a_caller_lists_the_inbox)
    await services.sync.sync_account(account)

    told = recorded(services, account)[told_before:]
    created = [i for kind, i, _ in told if kind == "message.created"]
    assert created == [listed["New"]]
    message = await services.mailbox.get_message(ADMIN, account, listed["New"])
    assert message.subject == "New"


# --- a list and a change at the same time -------------------------------------------


async def test_a_list_answers_while_a_message_on_its_page_is_moved(
    imap_services: Services,
    imap_account_id: str,
    imap_server: FakeMailBox,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    services, account = imap_services, imap_account_id
    await services.sync.sync_account(account)
    moved = (await ids_by_subject(services, account))["Mail 1"]
    imap_server.add("INBOX", 9, make_message("New"))

    async def a_caller_moves_it() -> None:
        answer = await services.mailbox.update_message(
            ADMIN, account, moved, MessageUpdate(folder_ids=[ARCHIVE])
        )
        assert answer.id == moved

    # The list reads the new mail's header. Meanwhile another mail of its
    # page moves.
    before_the_first_headers(services, account, monkeypatch, a_caller_moves_it)
    page = await ids_by_subject(services, account)

    assert page["Mail 1"] == moved
    assert "New" in page
    message = await services.mailbox.get_message(ADMIN, account, moved)
    assert message.folder_ids == [ARCHIVE]


async def test_a_list_answers_while_a_message_on_its_page_is_deleted_for_good(
    imap_services: Services,
    imap_account_id: str,
    imap_server: FakeMailBox,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    services, account = imap_services, imap_account_id
    await services.sync.sync_account(account)
    deleted = (await ids_by_subject(services, account))["Mail 1"]
    imap_server.add("INBOX", 9, make_message("New"))

    async def a_caller_deletes_it() -> None:
        await services.mailbox.delete_message(ADMIN, account, deleted, permanent=True)

    before_the_first_headers(services, account, monkeypatch, a_caller_deletes_it)
    page = await ids_by_subject(services, account)

    # The page was read before the deletion and names the mail as it was.
    assert page["Mail 1"] == deleted
    assert "New" in page
    with pytest.raises(NotFoundError):
        await services.mailbox.get_message(ADMIN, account, deleted)


async def test_a_list_answers_while_a_pass_follows_a_move_by_another_client(
    imap_services: Services,
    imap_account_id: str,
    imap_server: FakeMailBox,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    services, account = imap_services, imap_account_id
    await services.sync.sync_account(account)
    moved = (await ids_by_subject(services, account))["Mail 1"]
    imap_server.add("INBOX", 9, make_message("New"))

    async def another_client_moves_it_and_a_pass_runs() -> None:
        imap_server.other_client_moves("INBOX", 1, "Archive", 5)
        await services.sync.sync_account(account)

    before_the_first_headers(
        services, account, monkeypatch, another_client_moves_it_and_a_pass_runs
    )
    page = await ids_by_subject(services, account)

    assert page["Mail 1"] == moved
    message = await services.mailbox.get_message(ADMIN, account, moved)
    assert message.folder_ids == [ARCHIVE]


# --- a list before the pass ---------------------------------------------------------


async def test_a_list_keeps_the_id_of_a_message_another_client_moved(
    imap_services: Services, imap_account_id: str, imap_server: FakeMailBox
) -> None:
    services, account = imap_services, imap_account_id
    await services.sync.sync_account(account)
    moved = (await ids_by_subject(services, account))["Mail 1"]
    told_before = len(recorded(services, account))
    imap_server.other_client_moves("INBOX", 1, "Archive", 5)

    # No pass saw the move yet. The list of the new folder asks for one.
    assert await archive_by_subject(services, account) == {"Mail 1": moved}

    told = recorded(services, account)[told_before:]
    assert [(kind, i) for kind, i, _ in told] == [("message.updated", moved)]
    message = await services.mailbox.get_message(ADMIN, account, moved)
    assert message.folder_ids == [ARCHIVE]


async def test_a_copy_in_another_folder_gets_an_id_of_its_own(
    imap_services: Services, imap_account_id: str, imap_server: FakeMailBox
) -> None:
    services, account = imap_services, imap_account_id
    await services.sync.sync_account(account)
    first = (await ids_by_subject(services, account))["Mail 1"]
    told_before = len(recorded(services, account))
    # The same Message-ID a second time, and the first is still there.
    imap_server.add("Archive", 5, make_message("Mail 1"))

    copy = (await archive_by_subject(services, account))["Mail 1"]

    assert copy != first
    told = recorded(services, account)[told_before:]
    assert [(kind, i) for kind, i, _ in told] == [("message.created", copy)]
    assert (await ids_by_subject(services, account))["Mail 1"] == first


async def test_a_list_answers_where_the_pass_it_asks_for_fails(
    imap_services: Services,
    imap_account_id: str,
    imap_server: FakeMailBox,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    services, account = imap_services, imap_account_id
    await services.sync.sync_account(account)
    imap_server.other_client_moves("INBOX", 1, "Archive", 5)

    async def down() -> dict[str, str]:
        raise ProviderUnavailableError("the server did not answer")

    # Only a pass asks for the states of the folders.
    monkeypatch.setattr(services.adapters.get(account), "folder_states", down)

    assert list(await archive_by_subject(services, account)) == ["Mail 1"]


async def test_a_message_we_stored_ourselves_waits_for_no_pass(
    imap_services: Services, imap_account_id: str, imap_server: FakeMailBox
) -> None:
    """``public_ids`` syncs first for a list only, not for the sent copy
    or the draft the service stored a moment ago."""
    services, account = imap_services, imap_account_id
    await services.sync.sync_account(account)
    passes = services.sync.state(account).passes
    imap_server.other_client_moves("INBOX", 1, "Archive", 5)
    page = await services.adapters.get(account).list_messages(
        ARCHIVE, limit=50, cursor=None, search=None
    )
    [item] = page.items

    await services.sync.public_ids(account, [(item.id, ARCHIVE)], listed=False)

    assert services.sync.state(account).passes == passes
