"""``sorting``: does this message in the inbox belong to a listed group,
by its sender or by what it says, and which folder is the group's?

The sender rules of the list decide first, in code. A model is asked only
for a message no sender rule settles, and only when a group of the list
has a topic: it chooses among the groups the sender matches alike, each
with a topic, or among every group with a topic when no rule matches, or
answers ``none``, with a quote the code looks up in the mail (decided
2026-11-24). A group chosen by its topic is acted on only where the owner
set ``by_topic`` to ``act``, else it is recorded. A message of a group is
moved from the inbox into the group's folder, which
is made first when it is missing, each folder above it as an action of its
own. A message already in another folder is the owner's choice and stays.
A group that is held has its moves recorded only, whatever the stage. With
the move the agent sets its keyword, so a message it sorted is known as
such also to a person and to a state file made anew (decided 2026-11-18).
The group is looked up again when the agent acts, against the list as it
is then: by its sender, so a sender added since reaches older mail
through ``backfill``, or by its name, for a group the model chose. See
docs/mailbox-agents/concept/agent-sorting.md.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping
from functools import cached_property

from benethos_mailbox_common.values import secret
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
    Trigger,
    load_prompt,
)
from ...errors import ConfigError
from ...records import LABEL, Decision, Evidence, FolderRef, MailMessage
from ...settings import PREFIX
from .groups import NONE, Group, Groups, Match, load_groups
from .schema import answer_for, parts, render, system_for

__all__ = ["NONE", "Sorting"]

# The senders in no group a report names at most, as candidates.
CANDIDATES = 10

# The version of the fixed text of the prompt.
PROMPT = "v1"


def _version(groups: Groups) -> str:
    """The version of a list: a digest of the groups as read, in JSON with
    sorted keys, so the same list gives the same version. A group without
    a topic is read without ``topic`` and ``by_topic``, so a list written
    before either existed keeps its version."""
    found = []
    for group in groups.groups:
        read = group.model_dump(mode="json")
        if group.topic is None:
            del read["topic"], read["by_topic"]
        found.append(read)
    normal = json.dumps({"groups": found}, sort_keys=True)
    return "list-" + secret.digest(normal)[:12]


def _fate(item: Shown) -> str:
    """What became of a message of a group: moved, held, recorded, recorded
    by topic, when the model chose a group that only records, or not moved,
    when its move was refused or not asked for."""
    moves = [a.done for a in item.actions if a.action is Action.MOVE_TO_FOLDER]
    if not moves:
        return "not moved"
    if any(moves):
        return "moved"
    details = item.decision.details
    if details.get("hold") == "yes":
        return "held"
    if details.get("match") == "topic" and details.get("by_topic") == "record":
        return "recorded by topic"
    return "recorded"


class Sorting(Agent):
    name = "sorting"
    version = "2"
    description = (
        "Moves mail from the inbox into the folder of its group, by its sender "
        "or, where a group has a topic, by what it says."
    )
    triggers = Trigger(routes={"message.created": Route.DECIDE})
    actions = frozenset(
        {Action.CREATE_FOLDER, Action.MOVE_TO_FOLDER, Action.ADD_KEYWORD}
    )
    limits = Limits(model_calls_per_message=1, model_calls_per_day=2000)
    requires = Requires(settings=("sorting_file",))
    # No $ in front: IMAP registers such keywords with meanings, as $Junk.
    default_keyword = "agent-sorted"
    # A group's name is the owner's own text: an evaluation report shows
    # it as label-<n>.
    report_labels = frozenset({NONE})

    # -- what it reads besides its settings -----------------------------------

    def prepare(self) -> None:
        """Read the list now, so a wrong one stops the start, and with it
        the version the decision is stored under."""
        _ = self.groups

    @cached_property
    def groups(self) -> Groups:
        """The list, read once. Reading it sets the version of the decision
        to the prompt's and a digest of the list, so a changed list is new
        work and each message is decided anew under it (decided 2026-11-18).
        A topic is part of the prompt the model reads."""
        path = self.settings.sorting_file
        if path is None:
            raise ConfigError(f"{PREFIX}SORTING_FILE is not set")
        found = load_groups(path)
        self.prompt_version = f"{PROMPT}-{_version(found)}"
        return found

    @cached_property
    def system(self) -> str:
        """The fixed text of the prompt, the groups to choose from follow."""
        return load_prompt(__package__ or "", "system", PROMPT)

    def asks_model(self) -> bool:
        """Only when a group of the list has a topic."""
        return self.groups.asks_model

    def may_create(self, path: str, folders: Mapping[str, FolderRef]) -> bool:
        # The list names whole paths: the folders above do not matter.
        return self.groups.may_create(path)

    # -- the contract -------------------------------------------------------------

    def admit(self, message: MailMessage) -> bool:
        """A message in the inbox the agent has not sorted before: one that
        carries its keyword was put back there by a person."""
        return message.in_role("inbox") and not message.has_keyword(self.keyword)

    def baseline(self, message: MailMessage) -> Decision:
        found = self._match(message)
        if found is None:
            return Decision(label=NONE, source="baseline", details={"match": "none"})
        group = found.group
        if group is None:
            return Decision(
                label=NONE,
                source="baseline",
                details={
                    "match": "ambiguous",
                    "groups": ",".join(g.name for g in found.groups),
                },
            )
        details = {"match": "group", "rule": found.kind.name.lower()}
        if group.hold:
            details["hold"] = "yes"
        return Decision(label=group.name, source="baseline", details=details)

    async def decide(self, message: MailMessage, context: Context) -> Decision:
        """The sender rules where they settle it, with no call. Else the
        model, once, among the groups to choose from."""
        address = message.sender.email if message.sender else None
        choice = self.groups.candidates(address)
        if not choice:
            return self.baseline(message)
        among = "senders" if self.groups.match(address) is not None else "all"
        answer = await context.model.ask(
            system=system_for(self.system, choice),
            content=render(message),
            evidence=parts(message),
            schema=answer_for([group.name for group in choice]),
        )
        said = answer.model_dump()
        group = self.groups.named(said["group"])
        if group is None:
            # none needs no quote: nothing is done on it (2026-11-24).
            return Decision(
                label=NONE,
                source="model",
                evidence=(Evidence(field=LABEL, value=NONE, quote="", found=True),),
                details={"match": "none", "among": among},
            )
        details = {"match": "topic", "among": among, "by_topic": group.by_topic}
        if group.hold:
            details["hold"] = "yes"
        return Decision(
            label=group.name,
            source="model",
            evidence=(Evidence(field=LABEL, value=group.name, quote=said["quote"]),),
            details=details,
        )

    async def effect(
        self, decision: Decision, message: MailMessage, context: Context
    ) -> list[ActionRequest]:
        if decision.details.get("match") == "topic":
            # The group the model chose, as the list says now.
            chosen = self.groups.named(decision.label)
            return [] if chosen is None else self._move(chosen, message, by_topic=True)
        # The group as the list says now, not as it said at the decision.
        found = self._match(message)
        group = found.group if found is not None else None
        if group is None:
            return []
        return self._move(group, message)

    def summarize(self, shown: list[Shown]) -> list[str]:
        """Per group what became of its messages, the senders in no group
        that wrote most often, as candidates for the list, and the senders
        left alone because two groups name them alike."""
        lines: list[str] = []
        fates: dict[str, Counter[str]] = {}
        for item in shown:
            if item.decision.label != NONE:
                fates.setdefault(item.decision.label, Counter())[_fate(item)] += 1
        if fates:
            lines.append("groups:")
            for name in sorted(fates):
                counted = fates[name]
                said = ", ".join(
                    f"{counted[fate]} {fate}"
                    for fate in (
                        "moved",
                        "recorded",
                        "recorded by topic",
                        "held",
                        "not moved",
                    )
                    if counted[fate]
                )
                lines.append(f"  {name}: {said}")
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

    def _match(self, message: MailMessage) -> Match | None:
        """The groups the sender of ``message`` belongs to, as the list
        says now."""
        return self.groups.match(message.sender.email if message.sender else None)

    def _move(
        self, group: Group, message: MailMessage, *, by_topic: bool = False
    ) -> list[ActionRequest]:
        """The folders from the top, the move, and with it the keyword. A
        held group asks for all of it to be recorded only, and so does a
        group the model chose by its topic unless the owner set it to act."""
        held = group.hold or (by_topic and group.by_topic == "record")
        # A code, never the group's name: a name is the owner's free text
        # and often names a person, which no log line may (decided
        # 2026-11-18).
        why = "held" if held else ("topic" if by_topic else "group")
        requests = [
            ActionRequest(
                Action.CREATE_FOLDER,
                message.ref,
                folder=path,
                why=why,
                held=held,
            )
            for path in group.folders
        ]
        requests.append(
            ActionRequest(
                Action.MOVE_TO_FOLDER,
                message.ref,
                folder=group.folder,
                why=why,
                held=held,
            )
        )
        # The keyword says the message was moved, so it is asked for after
        # the move. The executor takes nothing after a refused move, and
        # records only what follows a move recorded only, by the stage or
        # held: the keyword never stands without the move.
        requests.append(
            ActionRequest(
                Action.ADD_KEYWORD, message.ref, keyword=self.keyword, why="sorted"
            )
        )
        return requests
