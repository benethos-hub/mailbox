"""What every adapter shares: a batch id by id, a draft replaced."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import pytest

from benethos_mailbox_service.data.providers import rules
from benethos_mailbox_service.errors import (
    MailboxServiceError,
    NotFoundError,
    ProviderError,
    ProviderUnavailableError,
)


def _batch(lost_at: str) -> Callable[[str], Awaitable[str]]:
    async def one(message_id: str) -> str:
        if message_id == "gone":
            raise NotFoundError("no such message")
        if message_id == lost_at:
            raise ProviderUnavailableError("the mail server is not reachable")
        return f"done {message_id}"

    return one


async def test_a_lost_connection_first_fails_the_batch() -> None:
    with pytest.raises(ProviderUnavailableError):
        await rules.per_id(["a", "b"], _batch(lost_at="a"))


async def test_a_lost_connection_later_names_what_was_done() -> None:
    results = await rules.per_id(["a", "gone", "b", "c"], _batch(lost_at="b"))
    assert results["a"] == "done a"
    assert isinstance(results["gone"], NotFoundError)
    assert isinstance(results["b"], ProviderUnavailableError)
    assert isinstance(results["c"], ProviderUnavailableError)


async def test_a_draft_replaced_or_nothing() -> None:
    dropped: list[str] = []

    async def drop(name: str, fails: bool) -> None:
        if fails:
            raise ProviderUnavailableError(f"{name} stays")
        dropped.append(name)

    await rules.replaced("new", lambda: drop("old", False), lambda: drop("new", False))
    assert dropped == ["old"]
    with pytest.raises(ProviderUnavailableError, match="old stays"):
        await rules.replaced(
            "new", lambda: drop("old", True), lambda: drop("new", False)
        )
    assert dropped == ["old", "new"]
    with pytest.raises(ProviderError, match="the draft new replacing it stays"):
        await rules.replaced(
            "new", lambda: drop("old", True), lambda: drop("new", True)
        )


def test_a_note_keeps_the_failure() -> None:
    failure = ProviderUnavailableError("busy").noting("in the trash now")
    assert isinstance(failure, MailboxServiceError)
    assert failure.message == str(failure) == "busy: in the trash now"
