"""``sorting``: which category of its list does a message belong to,
in each dimension of the list, and what follows from it?

A list names one or more dimensions, each with its categories, and runs
them in order, a later one only after the categories of an earlier one
its ``when`` names. A dimension finds its category by the sender rules in
code first. A model is asked only for a message no rule settles, and only
when a category has a topic or a recognizer that asks one: it chooses
among the categories with a quote the code looks up in the mail (decided
2026-11-24). What follows from a category is named in its ``then``: a
keyword of the list, a move into a folder, a folder below the one it goes
to (decided 2026-11-25). A category chosen by its topic is moved only where
the owner set ``by_topic`` to ``act``, else the move is recorded. Of
several moves the one of the highest priority wins. The folder of a move is
made first when it is missing, each folder above it as an action of its
own. A message already in another folder is the owner's choice and stays.
A category that is held has what follows from it recorded only, whatever
the stage. With the move the agent sets its keyword, so a message it
sorted is known as such also to a person and to a state file made anew
(decided 2026-11-18). The category is looked up again when the agent acts,
against the list as it is then: by its sender, so a sender added since
reaches older mail through ``backfill``, or by its name, for a category the
model chose. A list of groups alone, the form before the chain, is one
dimension. See docs/mailbox-agents/concept/agent-sorting.md.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from functools import cached_property

from benethos_mailbox_common.values import text as text_values

from ...contract import (
    Action,
    ActionRequest,
    Agent,
    Context,
    Limits,
    Requires,
    Route,
    Shown,
    TracePart,
    Trigger,
)
from ...errors import ConfigError
from ...records import Decision, FolderRef, MailMessage
from ...settings import PREFIX
from .actions import Placed
from .dimensions import Chain
from .groups import NONE
from .lists import Listed, load_chain, used
from .lists import list_digest as _version
from .plan import classify, classify_rules, found_in, requests_for, to_decision
from .recognizers import PROMPT, Choice
from .summary import fates, parts_of

__all__ = ["NONE", "PROMPT", "Sorting", "_version"]

# The senders in no group a report names at most, as candidates.
CANDIDATES = 10


def _runs(when: Mapping[str, tuple[str, ...]], chosen: Mapping[str, str]) -> bool:
    """Whether ``when`` holds for the categories ``chosen`` so far."""
    return all(chosen.get(name) in allowed for name, allowed in when.items())


class Sorting(Agent):
    name = "sorting"
    version = "3"
    description = (
        "Sorts mail into the categories of its list, one dimension after "
        "another, by its sender or by what it says, and marks or files it as "
        "each category says."
    )
    triggers = Trigger(routes={"message.created": Route.DECIDE})
    actions = frozenset(
        {Action.CREATE_FOLDER, Action.MOVE_TO_FOLDER, Action.ADD_KEYWORD}
    )
    # Two recognizers of a list may ask the model, each once.
    limits = Limits(model_calls_per_message=2, model_calls_per_day=2000)
    requires = Requires(settings=("sorting_file",))
    # No $ in front: IMAP registers such keywords with meanings, as $Junk.
    default_keyword = "agent-sorted"
    # A category's name is the owner's own text: an evaluation report shows
    # it as label-<n>.
    report_labels = frozenset({NONE})

    # -- what it reads besides its settings -----------------------------------

    def prepare(self) -> None:
        """Read the list now, so a wrong one stops the start, and with it
        the version the decision is stored under."""
        _ = self.listed

    @cached_property
    def listed(self) -> Listed:
        """The list, read once. Reading it sets the version of the decision
        to the prompt's and a digest of the list, so a changed list is new
        work and each message is decided anew under it (decided 2026-11-18).
        A topic is part of the prompt the model reads."""
        path = self.settings.sorting_file
        if path is None:
            raise ConfigError(f"{PREFIX}SORTING_FILE is not set")
        found = load_chain(path)
        self.prompt_version = f"{PROMPT}-{found.version}"
        return found

    @property
    def chain(self) -> Chain:
        return self.listed.chain

    def asks_model(self) -> bool:
        """Only when a recognizer of the list asks the model."""
        return any(
            recognizer.asks_model(dimension)
            for recognizer in used(self.chain)
            for dimension in self.chain.dimensions
            if recognizer.applies(dimension)
        )

    def may_create(self, path: str, folders: Mapping[str, FolderRef]) -> bool:
        """A folder of a move of the list or one above it, and one a
        move_below names below a folder of the owner, one without a role."""
        if path in self.chain.folders():
            return True
        for below in self.chain.belows():
            parent = path.removesuffix(f"/{below}")
            if parent == path:
                continue
            found = folders.get(parent)
            if found is not None and found.role is None:
                return True
        return False

    def keywords(self) -> frozenset[str]:
        """Its own keyword and every keyword the list sets in ``then``
        (decided 2026-11-25)."""
        return frozenset({self.keyword}) | self.chain.keywords()

    def trace_parts(self, decision: Decision) -> list[TracePart]:
        """A part for each dimension that ran: its name, how its category
        was found, the category as ``label-<n>`` by its place in the list,
        and whether its quote was found. Never the name of a category."""
        return parts_of(self.chain, decision)

    def backfill_folder(self, folder: FolderRef) -> bool:
        """A folder without a role, when the list takes up mail that
        arrives there."""
        return self.chain.on.arrival == "folders" and folder.role is None

    # -- the contract -------------------------------------------------------------

    def admit(self, message: MailMessage) -> bool:
        """A message in the inbox the agent has not sorted before: one that
        carries its keyword was put back there by a person. With
        ``on.arrival`` ``folders`` also one in a folder without a role."""
        if message.has_keyword(self.keyword):
            return False
        if message.in_role("inbox"):
            return True
        return self.chain.on.arrival == "folders" and any(
            folder.role is None for folder in message.folders
        )

    def baseline(self, message: MailMessage) -> Decision:
        chosen: dict[str, str] = {}
        choices: list[Choice | None] = []
        for dimension in self.chain.dimensions:
            if not _runs(dimension.when, chosen):
                choices.append(None)
                continue
            found = classify_rules(dimension, message)
            chosen[dimension.name] = found.category
            choices.append(found)
        return to_decision(self.chain, choices)

    async def decide(self, message: MailMessage, context: Context) -> Decision:
        """The sender rules where they settle it, with no call. Else the
        model, once per recognizer that asks it, among the categories to
        choose from."""
        chosen: dict[str, str] = {}
        choices: list[Choice | None] = []
        for dimension in self.chain.dimensions:
            if not _runs(dimension.when, chosen):
                choices.append(None)
                continue
            found = await classify(dimension, message, context)
            chosen[dimension.name] = found.category
            choices.append(found)
        return to_decision(self.chain, choices)

    async def effect(
        self, decision: Decision, message: MailMessage, context: Context
    ) -> list[ActionRequest]:
        # The categories as the list says now, not as it said at the decision.
        found = found_in(self.chain, decision, message)
        return requests_for(
            found, Placed.of(message), self.keyword, mark_done=self.chain.mark_done
        )

    def summarize(self, shown: list[Shown]) -> list[str]:
        """Per dimension and category what became of its messages, the
        senders in no category of the first dimension that wrote most often,
        as candidates for the list, and the senders left alone because two
        categories name them alike."""
        lines = fates(self.chain, shown)
        # A sender two groups with a topic name, which the model left in
        # none, is in the list already: no candidate.
        unknown = Counter(
            item.sender.lower()
            for item in shown
            if item.sender
            and item.decision.details.get("match") == "none"
            and item.decision.details.get("among") != "senders"
        )
        if unknown:
            lines.append("senders in no group, candidates for the list:")
            lines += [
                f"  {sender} ({text_values.plural(count, 'message')})"
                for sender, count in unknown.most_common(CANDIDATES)
            ]
        alike = Counter(
            (item.sender.lower(), item.decision.details.get("groups", ""))
            for item in shown
            if item.sender and item.decision.details.get("match") == "ambiguous"
        )
        if alike:
            lines.append("left alone, two groups name the sender alike:")
            lines += [
                f"  {sender}: {groups} ({text_values.plural(count, 'message')})"
                for (sender, groups), count in alike.most_common()
            ]
        return lines
