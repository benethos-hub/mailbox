"""The operations an account offers its caller (UNIFORM U1): its rights
there and what the account can do together, from the one table the
domain checks."""

from __future__ import annotations

from fastapi.testclient import TestClient

from benethos_mailbox_common.mail import marks as words
from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.data.models import Abilities, Capability, Grant, Mark
from benethos_mailbox_service.domain.accounts import operations

from ...conftest import bearer_for, memory_of, relearn

RIGHTS = [
    "list_messages",
    "update_message",
    "delete_message",
    "delete_message_permanent",
    "batch_messages",
    "list_threads",
    "create_draft",
    "send_message",
    "send_draft",
]


def test_what_the_account_cannot_do_is_left_out() -> None:
    reads = Abilities.of({Capability.SEND})
    assert operations(RIGHTS, reads) == ["list_messages", "send_message"]
    marks_alone = Abilities.of(set(), written={Mark.ANSWERED})
    assert "update_message" in operations(RIGHTS, marks_alone)
    trash = Abilities.of({Capability.TRASH})
    assert operations(RIGHTS, trash) == [
        "batch_messages",
        "delete_message",
        "list_messages",
    ]
    drafts = Abilities.of({Capability.DRAFTS, Capability.SEND})
    assert {"create_draft", "send_draft", "send_message"} <= set(
        operations(RIGHTS, drafts)
    )


def test_what_the_rights_leave_out_is_left_out() -> None:
    every = Abilities.of(set(Capability), written=set(Mark))
    assert operations(["list_messages"], every) == ["list_messages"]


def test_the_account_answers_them(
    app_client: TestClient, client: TestClient, services: Services, account_id: str
) -> None:
    memory_of(services, account_id).given = Abilities.of({Capability.DRAFTS})
    relearn(services, account_id)
    headers = bearer_for(
        services, Grant(accounts=[account_id], allow=["mail.read", "drafts", "send"])
    )
    found = app_client.get(f"/v1/accounts/{account_id}", headers=headers)
    assert found.status_code == 403  # get_account is a right of its own
    admin = client.get(f"/v1/accounts/{account_id}").json()
    assert "create_draft" in admin["operations"]
    assert "send_message" not in admin["operations"]
    me = app_client.get("/v1/me", headers=headers).json()
    [account] = me["accounts"]
    assert "list_drafts" in account["operations"]
    assert "send_draft" not in account["operations"]


def test_every_mark_has_its_words() -> None:
    assert {m.keyword for m in words.MARKS} == {m.value for m in Mark}
