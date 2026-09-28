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
