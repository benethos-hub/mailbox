"""The answers of the mailbox service that refuse a request, and those
that say it is away."""

from __future__ import annotations

import pytest

from benethos_mailbox_agents.errors import MailboxRefusedError, MailboxUnavailableError
from benethos_mailbox_agents.records import MessageRef
from benethos_mailbox_agents.sources.mailbox import Mailbox

from ..agents_fake import ACCOUNT, FakeService, wire_message

REF = MessageRef(account_id=ACCOUNT, message_id="m1")


async def test_what_an_account_cannot_do_is_a_refusal(
    fake_service: FakeService, mailbox: Mailbox
) -> None:
    """A 501 not_supported, as for a keyword on Gmail or POP3: the service
    is there, the request is refused."""
    fake_service.add(wire_message("m1"))
    fake_service.write_refusal = (501, "not_supported")

    with pytest.raises(MailboxRefusedError) as raised:
        await mailbox.add_keyword(REF, "agent-x")
    assert (raised.value.status, raised.value.reason) == (501, "not_supported")


@pytest.mark.parametrize("refusal", [(501, "not_implemented"), (503, "not_supported")])
async def test_any_other_answer_from_500_on_is_the_service_away(
    fake_service: FakeService, mailbox: Mailbox, refusal: tuple[int, str]
) -> None:
    fake_service.add(wire_message("m1"))
    fake_service.write_refusal = refusal

    with pytest.raises(MailboxUnavailableError):
        await mailbox.add_keyword(REF, "agent-x")
