"""The errors every layer raises."""

from __future__ import annotations

from benethos_mailbox_service.errors import (
    MessageNotFoundError,
    NotFoundError,
    missing,
    missing_message,
)


def test_missing_names_what_is_not_there() -> None:
    error = missing("folder", "f_1")
    assert type(error) is NotFoundError
    assert str(error) == "folder f_1 not found"
    assert str(missing("draft")) == "draft not found"


def test_a_missing_message_is_its_own_kind() -> None:
    assert isinstance(missing_message("msg_1"), MessageNotFoundError)
    assert str(missing_message("msg_1")) == "message msg_1 not found"
    assert str(missing_message()) == "message not found"
