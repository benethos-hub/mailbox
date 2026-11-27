"""A forward put into the drafts folder through the mailbox service, and
whether one is there: what is sent, and nothing more."""

from __future__ import annotations

import json

import pytest

from benethos_mailbox_agents.errors import MailboxRefusedError
from benethos_mailbox_agents.records import MessageRef
from benethos_mailbox_agents.sources.mailbox import Mailbox

from ..agents_fake import ACCOUNT, FakeService, wire_message

REF = MessageRef(account_id=ACCOUNT, message_id="m1")
TO = ("partner@example.org", "Desk@example.org")


def _posted(fake_service: FakeService) -> list[dict[str, object]]:
    return [
        json.loads(r.content)
        for r in fake_service.requests
        if r.method == "POST" and r.url.path.endswith("/drafts")
    ]


@pytest.mark.parametrize(
    ("forward_as", "reference"),
    [
        ("inline", {"message_id": "m1", "action": "forward"}),
        (
            "attachment",
            {"message_id": "m1", "action": "forward", "forward_as": "attachment"},
        ),
    ],
)
async def test_a_forward_is_drafted_with_no_text_of_its_own(
    fake_service: FakeService,
    mailbox: Mailbox,
    forward_as: str,
    reference: dict[str, str],
) -> None:
    fake_service.add(wire_message("m1"))

    draft = await mailbox.draft_forward(REF, TO, forward_as)

    assert draft == "draft1"
    assert _posted(fake_service) == [
        {
            "to": [{"email": address} for address in TO],
            "cc": [],
            "bcc": [],
            "subject": "",
            "text": "",
            "reference": reference,
        }
    ]
    assert [r.method for r in fake_service.requests] == ["POST"]


async def test_a_forward_drafted_is_found_by_its_recipients_and_reference(
    fake_service: FakeService, mailbox: Mailbox
) -> None:
    fake_service.add(wire_message("m1"))
    fake_service.add(wire_message("m2"))
    assert not await mailbox.forward_drafted(REF, TO)

    await mailbox.draft_forward(
        MessageRef(account_id=ACCOUNT, message_id="m2"), TO, "inline"
    )
    assert not await mailbox.forward_drafted(REF, TO)

    await mailbox.draft_forward(REF, TO, "inline")
    assert await mailbox.forward_drafted(REF, [a.upper() for a in reversed(TO)])
    assert not await mailbox.forward_drafted(REF, TO[:1])


async def test_an_account_without_drafts_refuses_it(
    fake_service: FakeService, mailbox: Mailbox
) -> None:
    fake_service.add(wire_message("m1"))
    fake_service.write_refusal = (501, "not_supported")

    with pytest.raises(MailboxRefusedError):
        await mailbox.draft_forward(REF, TO, "inline")
