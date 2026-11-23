"""``awaiting_reply``: does this sent message expect an answer, and has one come?

A sent message the model finds expecting a reply becomes an open item due
after MAILBOX_AGENTS_REPLY_DAYS working days, Monday to Friday. It closes
when a later message from another sender arrives in its thread, an
automatic answer not counted, or when a person takes the keyword off. A
new message of the sender in the same thread restarts the deadline and
does not count as a reply. An item past its deadline gets the keyword on
the sent message, which stays where it is. See
docs/mailbox-agents/concept/agent-awaiting-reply.md.

Known misses, counted by the evaluation rather than argued away: an answer
that comes as a new mail outside the thread, an answer by telephone, and
several recipients of whom one answers.
"""

from __future__ import annotations

from datetime import datetime
from functools import cached_property

from ...contract import (
    Action,
    ActionRequest,
    Agent,
    Context,
    Limits,
    Route,
    Trigger,
    load_prompt,
)
from ...errors import MessageGoneError
from ...records import (
    DISCARD_ROLES,
    KEYWORD_REMOVED,
    LABEL,
    MESSAGE_DISCARDED,
    MESSAGE_GONE,
    Decision,
    Evidence,
    MailMessage,
    OpenItem,
)
from .schema import Answer, parts, render
from .text import add_working_days, address, asks, automatic

__all__ = ["AwaitingReply"]

EXPECTS, NO_REPLY, INCOMING = "expects_reply", "no_reply", "incoming"

# Why an item closes when a later message of its thread comes: a reply of
# another sender, or a new message of its own sender.
REPLIED, FOLLOWED_UP = "replied", "followed_up"
# The items the tick takes the keyword off while it is still noted as set.
# One closed as keyword_removed, message_gone or discarded is never asked
# about.
CLOSED_WITH_KEYWORD = (REPLIED, FOLLOWED_UP)


def _sent(message: MailMessage) -> bool:
    return message.in_role("sent")


def _when(message: MailMessage, fallback: datetime) -> datetime:
    return message.date or message.received or fallback


class AwaitingReply(Agent):
    name = "awaiting_reply"
    version = "2"
    description = "Marks sent mail that still waits for an answer after its deadline."
    triggers = Trigger(
        routes={
            "message.sent": Route.DECIDE,
            "message.created": Route.DECIDE,
            "message.updated": Route.OBSERVE,
        },
        tick=True,
    )
    actions = frozenset({Action.ADD_KEYWORD, Action.REMOVE_KEYWORD})
    limits = Limits(model_calls_per_message=1, model_calls_per_day=2000)
    default_keyword = "agent-awaiting-reply"
    report_labels = frozenset({EXPECTS, NO_REPLY, INCOMING})
    prompt_version = "v2"

    @cached_property
    def system(self) -> str:
        return load_prompt(__package__ or "", "system", self.prompt_version)

    # -- the contract -------------------------------------------------------------

    def admit(self, message: MailMessage) -> bool:
        """A message sent, or one received into the inbox within a thread."""
        return _sent(message) or (
            message.in_role("inbox") and message.thread_id is not None
        )

    def baseline(self, message: MailMessage) -> Decision:
        if not _sent(message):
            return Decision(label=INCOMING, source="baseline")
        return Decision(
            label=EXPECTS if asks(message.text) else NO_REPLY, source="baseline"
        )

    async def decide(self, message: MailMessage, context: Context) -> Decision:
        if not _sent(message):
            # What a received message does is a rule: it may close an item.
            return Decision(label=INCOMING, source="baseline")
        answer = await context.model.ask(
            system=self.system,
            content=render(message),
            evidence=parts(message),
            schema=Answer,
        )
        label = EXPECTS if answer.expects_reply else NO_REPLY
        return Decision(
            label=label,
            source="model",
            evidence=(Evidence(field=LABEL, value=label, quote=answer.quote),),
        )

    async def effect(
        self, decision: Decision, message: MailMessage, context: Context
    ) -> list[ActionRequest]:
        if decision.label == INCOMING:
            return await self._received(message, context)
        return await self._written(decision, message, context)

    async def _earlier(
        self, message: MailMessage, context: Context
    ) -> list[tuple[OpenItem, MailMessage]]:
        """The open items of the message's thread other than its own, each
        with its sent message, when that came before this one."""
        if message.thread_id is None:
            return []
        now = context.now()
        found = []
        items = await context.items.in_thread(message.ref.account_id, message.thread_id)
        for item in items:
            if item.ref == message.ref:
                continue
            try:
                sent = await context.reader.message(item.ref)
            except MessageGoneError:
                # Deleted since: no reply can be awaited for it any more,
                # and it holds up no other message of its thread.
                await context.items.close(item.ref, MESSAGE_GONE)
                continue
            if _when(sent, now) <= _when(message, now):
                found.append((item, sent))
        return found

    def _take_off(self, item: OpenItem) -> list[ActionRequest]:
        if not item.keyword_set:
            return []
        return [
            ActionRequest(
                Action.REMOVE_KEYWORD, item.ref, keyword=self.keyword, why="closed"
            )
        ]

    async def _received(
        self, message: MailMessage, context: Context
    ) -> list[ActionRequest]:
        """A later message from another sender closes the items of its
        thread. An automatic answer does not."""
        if automatic(message):
            return []
        requests: list[ActionRequest] = []
        sender = address(message)
        for item, sent in await self._earlier(message, context):
            owner = address(sent)
            if sender and sender == owner:
                continue
            await context.items.close(item.ref, REPLIED)
            requests += self._take_off(item)
        return requests

    async def _written(
        self, decision: Decision, message: MailMessage, context: Context
    ) -> list[ActionRequest]:
        """A new message of the sender in the thread restarts the deadline:
        an earlier item closes if this one waits itself, and starts again
        from this message if it does not."""
        due = add_working_days(_when(message, context.now()), self.settings.reply_days)
        expects = decision.label == EXPECTS
        requests: list[ActionRequest] = []
        for item, _ in await self._earlier(message, context):
            requests += self._take_off(item)
            if expects:
                await context.items.close(item.ref, FOLLOWED_UP)
            else:
                await context.items.restart(item.ref, due)
        if expects and not await self._answered(message, context):
            await context.items.open(message.ref, message.thread_id, due)
        return requests

    async def _answered(self, message: MailMessage, context: Context) -> bool:
        """Whether its thread already holds a later answer from someone else,
        automatic ones not counted: a reply taken up before the message it
        answers, by a backfill or a backoff, closes nothing, so it is
        looked for here."""
        if message.thread_id is None:
            return False
        now = context.now()
        thread = await context.reader.thread(message.ref.account_id, message.thread_id)
        me = address(message)
        sent = _when(message, now)
        for other in thread.messages:
            sender = address(other)
            if (
                other.ref != message.ref
                and sender not in ("", me)
                and not automatic(other)
                and _when(other, now) > sent
            ):
                return True
        return False

    async def observe(
        self, message: MailMessage, context: Context
    ) -> list[ActionRequest]:
        """A message moved to the trash, junk or spam closes its item: no
        keyword is set there, and the owner discarded it. A keyword a person
        took off closes the item as well."""
        item = await context.items.get(message.ref)
        if item is None or not item.is_open:
            return []
        if any(folder.role in DISCARD_ROLES for folder in message.folders):
            await context.items.close(message.ref, MESSAGE_DISCARDED)
        elif item.keyword_set and not message.has_keyword(self.keyword):
            await context.items.close(message.ref, KEYWORD_REMOVED)
        return []

    async def tick(self, now: datetime, context: Context) -> list[ActionRequest]:
        """The items past their deadline get the keyword. The runtime notes
        on the item whether it was set. An item closed by a reply or a new
        message whose keyword is still noted as set has it taken off: its
        removal in the step may have failed, and a step run again finds no
        open item to take it off from."""
        requests = []
        for item in await context.items.due(now):
            requests.append(
                ActionRequest(
                    Action.ADD_KEYWORD, item.ref, keyword=self.keyword, why="due"
                )
            )
        for item in await context.items.marked_closed(CLOSED_WITH_KEYWORD):
            requests += self._take_off(item)
        return requests
