"""``invoices``: is this message an invoice?

The model answers whether a message is an invoice, and for one that is
not, which near miss it is. The agent looks at the inbox and at the
folders its settings name. An invoice gets the keyword. One in a folder it
looks in moves into the subfolder below that folder, made when missing, so
the folder says whose invoice it is. One in the inbox stays there, unless
an inbox folder is set, and gets an open item: when a person or
``sorting`` moves it into a folder the agent looks in, the update of the
message reaches the agent, which moves it on into the subfolder without a
new model call. The item is opened also when an inbox folder is set, as
its move may not be taken, and closes when the message reaches it. The
inbox folder is an end station: where the settings take it in, an invoice
there is marked and stays. A message that carries its keyword and that
its state file does not know is skipped. Who put a message into a folder
does not matter: ``sorting``, a rule of the mail server or the owner by
hand. The agent knows nothing of groups and names no supplier (agent
version 5).
See docs/mailbox-agents/concept/agent-invoices.md.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from datetime import UTC, datetime
from functools import cached_property

from ...contract import (
    Action,
    ActionRequest,
    Agent,
    Context,
    Limits,
    Route,
    Shown,
    Trigger,
    load_prompt,
)
from ...records import LABEL, Decision, Event, Evidence, FolderRef, MailMessage
from .baseline import baseline
from .folders import Places
from .schema import Answer, parts, render

__all__ = ["FILED", "MOVED_ELSEWHERE", "NO_DEADLINE", "Invoices"]

# An open item of an invoice has no deadline: the agent has no tick.
NO_DEADLINE = datetime(9999, 12, 31, tzinfo=UTC)

# Why an open item closes: the invoice reached a folder the agent looks in
# and was filed, or went to a folder it does not look in.
FILED = "filed"
MOVED_ELSEWHERE = "moved_elsewhere"


class Invoices(Agent):
    name = "invoices"
    version = "6"
    description = (
        "Marks invoices, and moves one into the subfolder of the folder it lies in."
    )
    triggers = Trigger(events=frozenset({"message.created", "message.updated"}))
    actions = frozenset(
        {Action.ADD_KEYWORD, Action.MOVE_TO_FOLDER, Action.CREATE_FOLDER}
    )
    limits = Limits(model_calls_per_message=1, model_calls_per_day=2000)
    default_keyword = "agent-invoice"
    report_labels = frozenset({"invoice", "other"})
    report_fields = frozenset({"near_miss"})
    prompt_version = "v5"
    # A marked invoice its state file does not know stays where it lies,
    # also one the owner took out of its subfolder (decided 2026-11-19).
    skip_marked = True

    # -- what it reads besides its settings -----------------------------------

    def prepare(self) -> None:
        """Read the folders now, so a wrong setting stops the start."""
        _ = self.places

    @cached_property
    def places(self) -> Places:
        found = self.settings
        return Places.read(
            found.invoices_folders,
            found.invoices_subfolder,
            found.invoices_inbox_folder,
        )

    def folders_needed(self) -> tuple[str, ...]:
        return self.places.needed()

    def backfill_folder(self, folder: FolderRef) -> bool:
        return self.places.looks_in(folder)

    def may_create(self, path: str, folders: Mapping[str, FolderRef]) -> bool:
        return self.places.may_create(path, folders)

    def describe_folders(self, folders: Mapping[str, FolderRef]) -> list[str]:
        return self.places.describe(folders)

    @cached_property
    def system(self) -> str:
        return load_prompt(__package__ or "", "system", self.prompt_version)

    # -- the contract -------------------------------------------------------------

    def select(self, event: Event) -> Route | None:
        if event.type == "message.created":
            return Route.DECIDE
        if event.type == "message.updated":
            return Route.OBSERVE
        return None

    def admit(self, message: MailMessage) -> bool:
        return self._looked_in(message) is not None

    def baseline(self, message: MailMessage) -> Decision:
        return baseline(message)

    async def decide(self, message: MailMessage, context: Context) -> Decision:
        answer = await context.model.ask(
            system=self.system,
            content=render(message),
            evidence=parts(message),
            schema=Answer,
        )
        label, quote, near_miss = answer.label, answer.quote, answer.near_miss
        evidence = [Evidence(field=LABEL, value=label, quote=quote)]
        fields: dict[str, str] = {}
        if label == "other" and near_miss != "none":
            fields["near_miss"] = near_miss
            evidence.append(Evidence(field="near_miss", value=near_miss, quote=quote))
        return Decision(
            label=label, source="model", fields=fields, evidence=tuple(evidence)
        )

    async def effect(
        self, decision: Decision, message: MailMessage, context: Context
    ) -> list[ActionRequest]:
        if decision.label != "invoice":
            return []
        requests = [
            ActionRequest(
                Action.ADD_KEYWORD, message.ref, keyword=self.keyword, why="invoice"
            )
        ]
        # Where it lies when the agent acts, not when it was decided.
        folder = self._looked_in(message)
        if folder is None:
            return requests
        if folder.role == "inbox":
            # It stays, or its move into the inbox folder may not be taken,
            # the folder missing or the stage below full: a move into a
            # folder the agent looks in, by a person or by sorting, reaches
            # it as an update (observe). One that reaches the inbox folder
            # closes the item, as filed where the agent looks in it.
            await context.items.open(message.ref, message.thread_id, NO_DEADLINE)
        return requests + self._file(message, folder)

    async def observe(
        self, message: MailMessage, context: Context
    ) -> list[ActionRequest]:
        """An update of an invoice marked in the inbox: once it lies in a
        folder the agent looks in, it moves on into the subfolder, with no
        model call, and its item closes. One that reached the inbox folder
        where the agent looks in it closes its item as filed and stays.
        One moved anywhere else closes its item and stays.

        An item closed as filed whose message still lies in a folder the
        agent looks in is filed again: the item closes before the actions
        are taken, and a mailbox service away in between brings the same
        update back. The executor skips what is already there."""
        item = await context.items.get(message.ref)
        if item is None or message.in_role("inbox"):
            return []
        if not item.is_open and item.reason != FILED:
            return []
        folder = self._looked_in(message)
        if folder is None:
            if item.is_open:
                await context.items.close(message.ref, MOVED_ELSEWHERE)
            return []
        await context.items.close(message.ref, FILED)
        return self._file(message, folder)

    def summarize(self, shown: list[Shown]) -> list[str]:
        """The senders of invoices marked and left where they lay, with how
        many each sent: candidates for a group of ``sorting``, so their
        invoices reach a folder of their own. An invoice marked in the
        inbox folder counts too, although it is where it belongs: ``shown``
        names no folder, so it cannot be told from one left in the inbox."""
        counted = Counter(
            item.sender.lower()
            for item in shown
            if item.sender
            and item.decision.label == "invoice"
            and item.decision.actionable
            and not any(a.action is Action.MOVE_TO_FOLDER for a in item.actions)
        )
        if not counted:
            return []
        return ["invoices marked and not moved, by sender:"] + [
            f"  {sender} ({count} invoice{'s' if count > 1 else ''})"
            for sender, count in counted.most_common()
        ]

    # -- where an invoice goes ------------------------------------------------------

    def _looked_in(self, message: MailMessage) -> FolderRef | None:
        """The folder of the message the agent looks in, if any."""
        return next((f for f in message.folders if self.places.looks_in(f)), None)

    def _file(self, message: MailMessage, folder: FolderRef) -> list[ActionRequest]:
        """The folders to make and the move, for an invoice in ``folder``:
        to the inbox folder from the inbox, to the subfolder from a folder
        it looks in. Nothing when the settings name no place, nor from the
        inbox folder."""
        target = self.places.target(folder)
        if target is None:
            return []
        if folder.role == "inbox":
            return [
                ActionRequest(
                    Action.MOVE_TO_FOLDER, message.ref, folder=target, why="inbox"
                )
            ]
        return [
            ActionRequest(
                Action.CREATE_FOLDER, message.ref, folder=path, why="subfolder"
            )
            for path in self.places.steps(folder)
        ] + [
            ActionRequest(
                Action.MOVE_TO_FOLDER, message.ref, folder=target, why="subfolder"
            )
        ]
