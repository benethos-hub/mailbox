"""A list that gives messages their ids, at the same time as a sync pass
or a change of ours, and before a pass saw what another program did: the
feed tells no id the index does not hold, the list answers, and a
message keeps its id."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import pytest

from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.data.providers import ThreadHeaders

from ...conftest import ADMIN
from ...imap_fake import FakeMailBox, make_message
from ..sync_helpers import ids_by_subject, recorded


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
