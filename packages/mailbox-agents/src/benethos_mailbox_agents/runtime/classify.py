"""An agent's decision on one message, for a peer that asks: read, never
acted on.

The message is read through :class:`ReadOnlyMailbox`, as ``eval`` reads
it, and the agent's effect is never asked. A decision the worker stored
for the message under the same prompt version and model is taken as it
is, refreshed like the worker refreshes it. Otherwise the agent decides,
its evidence checked, and its model calls are kept in its state file as
the worker keeps them, where they count against its limits of the day:
the calls for one message in a day against its limit per message.
Nothing else is written: the decision is not stored, and an open item
the agent would open is refused. One message
at a time. See docs/mailbox-agents/concept/a2a.md.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from datetime import datetime

from ..contract import PASSED_BY, Agent, Reader
from ..errors import (
    AnswerRefusedError,
    ContractError,
    LimitReachedError,
    MailboxRefusedError,
    MessageGoneError,
    UnavailableError,
)
from ..logbook import messages, record
from ..records import (
    LABEL,
    Classified,
    Decision,
    MessageRef,
    NotClassified,
    OpenItem,
)
from ..store import Store
from .items import StoredItems
from .model import Asker, start_of_day
from .reader import ReadOnlyMailbox
from .steps import decide_checked, make_calls, make_context

__all__ = ["PeerClassifier", "told"]


class _ReadItems:
    """The agent's open items to read: a classification for a peer opens,
    restarts and closes none."""

    def __init__(self, items: StoredItems) -> None:
        self._items = items

    async def open(self, ref: MessageRef, thread_id: str | None, due: datetime) -> None:
        raise ContractError("a classification for a peer opens no item")

    async def restart(self, ref: MessageRef, due: datetime) -> None:
        raise ContractError("a classification for a peer restarts no item")

    async def get(self, ref: MessageRef) -> OpenItem | None:
        return await self._items.get(ref)

    async def in_thread(self, account_id: str, thread_id: str) -> list[OpenItem]:
        return await self._items.in_thread(account_id, thread_id)

    async def due(self, now: datetime) -> list[OpenItem]:
        return await self._items.due(now)

    async def close(self, ref: MessageRef, reason: str) -> None:
        raise ContractError("a classification for a peer closes no item")

    async def marked_closed(self, reasons: Sequence[str]) -> list[OpenItem]:
        return await self._items.marked_closed(reasons)


def told(agent: Agent, decision: Decision) -> Classified:
    """What a peer is told of ``decision``: no quote, no detail. Its
    fields only when they are categories of the owner's list, never a
    value taken from the mail."""
    found = {item.field: item.found is True for item in decision.evidence}
    fields = dict(decision.fields) if agent.peer_fields else {}
    return Classified(
        agent=agent.label,
        version=agent.prompt_version or agent.version,
        label=decision.label,
        source=decision.source,
        fields=fields,
        found={LABEL: found.get(LABEL, True)}
        | {name: found.get(name, True) for name in fields},
        refused=decision.refused,
    )


class PeerClassifier:
    """Classifies one message at a time for a peer."""

    def __init__(
        self,
        agent: Agent,
        *,
        reader: Reader,
        gateway: Asker,
        store: Store,
        now: Callable[[], datetime],
    ) -> None:
        self.agent = agent
        self._reader = ReadOnlyMailbox(reader)
        self._gateway = gateway
        self._store = store
        self._now = now
        self._lock = asyncio.Lock()

    async def classify(self, ref: MessageRef) -> Classified | NotClassified:
        async with self._lock:
            found = await self._classified(ref)
        outcome: str = "classified"
        if isinstance(found, NotClassified):
            outcome = found.reason
        elif found.refused:
            outcome = "refused"
        record(
            messages.PeerAsked(
                agent=self.agent.label, message_id=ref.message_id, outcome=outcome
            )
        )
        return found

    async def _classified(self, ref: MessageRef) -> Classified | NotClassified:
        try:
            return told(self.agent, await self._decision(ref))
        except MessageGoneError:
            return self._not("message_gone")
        except MailboxRefusedError:
            return self._not("message_refused")
        except LimitReachedError:
            return self._not("limit_reached")
        except AnswerRefusedError:
            return self._not("answer_refused")
        except UnavailableError:
            return self._not("unavailable")

    def _not(self, reason: str) -> NotClassified:
        return NotClassified.model_validate(
            {"agent": self.agent.label, "reason": reason}
        )

    async def _decision(self, ref: MessageRef) -> Decision:
        accounts = self.agent.settings.accounts
        if accounts and ref.account_id not in accounts:
            raise MailboxRefusedError(
                "the account is not one the agent works on", reason="not_admitted"
            )
        message = await self._reader.message(ref)
        passed = any(folder.role in PASSED_BY for folder in message.folders)
        if passed and not self.agent.admit(message):
            raise MailboxRefusedError(
                "the message is not one the agent takes", reason="not_admitted"
            )
        stored = self._store.step(
            ref, "decision", self.agent.prompt_version, self._gateway.model
        )
        if stored is not None:
            return self.agent.refresh(Decision.model_validate(stored.result), message)
        # A decision for a peer is not stored: its calls of the day count
        # against the limit per message, as one message's would.
        made = self._store.model_calls_for(ref, start_of_day(self._now()))
        if made >= self.agent.limits.model_calls_per_message:
            raise LimitReachedError(
                "the message had the model calls it may have today", per_day=False
            )
        calls = make_calls(
            self.agent, gateway=self._gateway, store=self._store, ref=ref, now=self._now
        )
        context = make_context(
            calls=calls,
            reader=self._reader,
            store=self._store,
            now=self._now,
            items=_ReadItems(StoredItems(self._store, self._now)),
        )
        return await decide_checked(self.agent, message, context, calls)
