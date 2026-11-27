"""What two kinds of agent share in the contract: a message as an action
sees it, the path of a folder, the keywords a list waits for."""

from __future__ import annotations

import dataclasses

import pytest

from benethos_mailbox_agents.agents.categorization import actions, groups
from benethos_mailbox_agents.contract import (
    Placed,
    folder_path,
    from_top,
    is_pattern,
    waits_for,
)
from benethos_mailbox_agents.records import FolderRef, MailMessage, MessageRef


def _message(*folders: FolderRef, keywords: tuple[str, ...] = ()) -> MailMessage:
    return MailMessage(
        ref=MessageRef(account_id="acc", message_id="m1"),
        subject="A subject",
        text="A text",
        folders=folders,
        keywords=keywords,
    )


INBOX = FolderRef(id="f1", name="Inbox", path="Inbox", role="inbox")
OWN = FolderRef(id="f2", name="Providers", path="Providers", role=None)


def test_placed_holds_where_a_message_lies_and_nothing_it_says() -> None:
    found = Placed.of(_message(INBOX, keywords=("agent-x",)))

    assert found.in_inbox
    assert found.own_folder is None
    assert found.keywords == ("agent-x",)
    names = {f.name for f in dataclasses.fields(Placed)}
    assert names.isdisjoint({"subject", "text", "sender", "attachments"})
    assert Placed.of(_message(OWN)).own_folder == "Providers"


def test_categorization_takes_them_from_the_contract() -> None:
    assert actions.Placed is Placed
    assert groups.folder_path is folder_path
    assert groups.from_top is from_top


@pytest.mark.parametrize(
    "path", ["/Bank", "Bank/", "A//B", "A/./B", "A/../B", " Bank", "Bank "]
)
def test_a_path_is_names_between_slashes(path: str) -> None:
    with pytest.raises(ValueError, match="names between /"):
        folder_path(path)


def test_from_top_names_every_folder_above() -> None:
    assert folder_path("Providers/Bank") == "Providers/Bank"
    assert from_top("Providers/Bank/Invoices") == (
        "Providers",
        "Providers/Bank",
        "Providers/Bank/Invoices",
    )


def test_a_pattern_is_a_keyword_or_the_start_of_one() -> None:
    assert is_pattern("agent-invoice")
    assert is_pattern("agent-partner-*")
    assert not is_pattern("Agent-Invoice")
    assert not is_pattern("agent-*-x")
    assert not is_pattern("*")


def test_a_list_waits_for_a_keyword_case_aside() -> None:
    patterns = ("agent-invoice", "agent-partner-*")

    assert waits_for(patterns, "Agent-Invoice")
    assert waits_for(patterns, "agent-partner-bank")
    assert not waits_for(patterns, "agent-invoices")
    assert not waits_for((), "agent-invoice")
