"""What an agent may reach while it works, each as a narrow protocol.

The runtime hands an agent a :class:`Context`. Through it the agent asks
the model, reads a thread and keeps its open items, and nothing else: it
never holds the mailbox client, the gateway client or the state file, so
it cannot take an action past the runtime. See
docs/mailbox-agents/concept/agent-contract.md and docs/mailbox-agents/concept/safety.md.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, TypeVar

from pydantic import BaseModel

from ..records import MailMessage, MessageRef, OpenItem, Thread

__all__ = ["Context", "Items", "Model", "Reader"]

T = TypeVar("T", bound=BaseModel)


class Model(Protocol):
    """One model call with a schema, as the runtime offers it to an agent.

    The runtime counts the calls against the agent's limits, records model,
    tokens and duration, and keeps ``evidence``, the parts of the mail in
    ``content`` without the frame around them, for the evidence check. The
    answer is validated against ``schema`` before it is returned.
    """

    async def ask(
        self,
        *,
        system: str,
        content: str,
        schema: type[T],
        evidence: Sequence[str],
    ) -> T:
        """The answer of the model, validated against ``schema``."""


class Reader(Protocol):
    """The mailbox, read-only."""

    async def message(self, ref: MessageRef) -> MailMessage:
        """The message as it is now."""

    async def thread(self, account_id: str, thread_id: str) -> Thread:
        """The conversation, its messages oldest first."""


class Items(Protocol):
    """The open items of an agent, with or without a deadline,
    docs/mailbox-agents/concept/state.md."""

    async def open(self, ref: MessageRef, thread_id: str | None, due: datetime) -> None:
        """Open an item for a message that has none, an item there already
        left as it is."""

    async def restart(self, ref: MessageRef, due: datetime) -> None:
        """Start an item again with a new deadline, unless a person closed it
        by taking the keyword off."""

    async def get(self, ref: MessageRef) -> OpenItem | None:
        """The item of a message, open or closed, or None."""

    async def in_thread(self, account_id: str, thread_id: str) -> list[OpenItem]:
        """The open items of a thread."""

    async def due(self, now: datetime) -> list[OpenItem]:
        """The open items whose deadline has come."""

    async def close(self, ref: MessageRef, reason: str) -> None:
        """Close the item of a message, saying why."""

    async def marked_closed(self, reasons: Sequence[str]) -> list[OpenItem]:
        """The closed items, closed for one of ``reasons``, whose keyword
        the agent set and has not seen taken off since."""


@dataclass(frozen=True, slots=True)
class Context:
    """What one step of an agent may reach. Its settings it has as
    ``self.settings``."""

    model: Model
    reader: Reader
    items: Items
    now: Callable[[], datetime]
