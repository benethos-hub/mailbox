"""The neutral model of a message and its filter."""

from __future__ import annotations

from benethos_mailbox_service.data.models import MessageFilter, MessageSummary


def summary(**flags: bool) -> MessageSummary:
    return MessageSummary(id="msg_1", account_id="acc_1", folder_id="f_1", **flags)


def test_the_flags_of_a_filter() -> None:
    unread = summary(unread=True, has_attachments=True)
    assert MessageFilter().flags_match(unread)
    assert MessageFilter(unread=True, has_attachments=True).flags_match(unread)
    assert not MessageFilter(starred=True).flags_match(unread)
    assert not MessageFilter(has_attachments=False).flags_match(unread)
    # The rest of the filter is left to the caller.
    assert MessageFilter(subject="nothing like it").flags_match(unread)


def test_a_message_says_by_default_its_account_cannot_tell() -> None:
    summary = MessageSummary(id="m1")
    assert summary.sender_check.result == "unknown"
    assert summary.sender_check.reason == "account"
    assert summary.model_dump(by_alias=True)["sender_check"] == {
        "result": "unknown",
        "domain": None,
        "matches_from": None,
        "method": None,
        "reason": "account",
    }
    # Each summary holds a check of its own.
    assert summary.sender_check is not MessageSummary(id="m2").sender_check
