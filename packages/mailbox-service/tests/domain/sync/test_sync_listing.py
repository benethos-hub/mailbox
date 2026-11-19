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
from benethos_mailbox_service.errors import NotFoundError

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
