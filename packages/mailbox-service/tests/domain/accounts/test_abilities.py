"""The domain answers 501 for what an adapter does not implement."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from benethos_mailbox_service.data.providers import Reads
from benethos_mailbox_service.domain.accounts import (
    deletes,
    deltas,
    drafts,
    sends,
    watches,
    writes,
)
from benethos_mailbox_service.errors import NotSupportedError


class OnlyReads:
    """An adapter that reads and does nothing else."""

    capabilities = frozenset()

    def __getattr__(self, name: str) -> Any:
        raise AttributeError(name)


@pytest.mark.parametrize(
    ("ask", "said"),
    [
        (writes, "no folders, read state, stars or keywords"),
        (deletes, "cannot delete"),
        (drafts, "no drafts"),
        (sends, "cannot send"),
        (watches, "polled"),
        (deltas, "compared"),
    ],
)
def test_what_an_adapter_lacks_is_not_supported(
    ask: Callable[[Reads], object], said: str
) -> None:
    with pytest.raises(NotSupportedError, match=said):
        ask(OnlyReads())  # type: ignore[arg-type]


def test_an_adapter_that_can_is_handed_back() -> None:
    class Sending:
        async def send(self, raw: bytes, sender: str, recipients: list[str]) -> None:
            pass

    adapter = Sending()
    assert sends(adapter) is adapter  # type: ignore[arg-type]
