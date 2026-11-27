"""The agent ``filing``: an actor that files mail into folders by its
keywords, by a list its owner wrote.

A message is taken up once it carries a keyword the list waits for, set
by another agent or by a person. From the inbox it goes to the folder of
the first rule with a move that fits, and below it to the folder of the
first rule with a below. In a folder of the owner it goes only below that
folder. After the move it gets the agent's keyword, ``agent-filed``, and
a message that carries it is not taken up again. No model, and nothing of
what a mail says: the agent sees it as ``Placed``. See
docs/mailbox-agents/concept/agent-filing.md.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from functools import cached_property

from ...contract import (
    Action,
    ActionRequest,
    Actor,
    Placed,
    Requires,
    Shown,
    from_top,
    list_version,
)
from ...errors import ConfigError
from ...records import Decision, FolderRef
from ...settings import PREFIX
from .rules import Rules, Target, load_rules

__all__ = ["Filing"]

# What became of the messages of a rule, in the order a report names it.
FATES = ("moved", "recorded", "left")


class Filing(Actor):
    name = "filing"
    version = "1"
    description = (
        "Files mail into folders by its keywords, by a list. No model, "
        "nothing of what a mail says."
    )
    actions = frozenset(
        {Action.CREATE_FOLDER, Action.MOVE_TO_FOLDER, Action.ADD_KEYWORD}
    )
    requires = Requires(settings=("filing_file",))
    default_keyword = "agent-filed"

    # -- what it reads besides its settings -----------------------------------

    def prepare(self) -> None:
        """Read the list now, so a wrong one stops the start. A list that
        waits for the agent's own keyword is refused: it would set itself
        off."""
        if self.rules.waits_for(self.keyword):
            raise ConfigError(
                "the filing list waits for the agent's own keyword: it would "
                "set itself off"
            )

    @cached_property
    def rules(self) -> Rules:
        """The list, read once. Its digest is the version of a decision, so
        a changed list is new work."""
        path = self.settings.filing_file
        if path is None:
            raise ConfigError(f"{PREFIX}FILING_FILE is not set")
        found = load_rules(path)
        self.prompt_version = "v1-" + list_version(found)
        return found

    # -- the actor ------------------------------------------------------------------

    def waits_for(self, keyword: str) -> bool:
        return self.rules.waits_for(keyword)

    def takes(self, placed: Placed) -> bool:
        """A message in the inbox or in one folder of the owner, which does
        not carry the agent's keyword yet."""
        if any(k.casefold() == self.keyword.casefold() for k in placed.keywords):
            return False
        return placed.in_inbox or placed.own_folder is not None

    def rule(self, placed: Placed) -> Decision:
        """The rule that leads to the target, as ``rule-<n>``, else none.
        The details name the places of the rules, never a folder."""
        target = self._target(placed)
        if target is None:
            return Decision(label="none", source="baseline")
        details = {
            part: str(place)
            for part, place in (("move", target.move), ("below", target.below))
            if place is not None
        }
        return Decision(
            label=f"rule-{target.place}", source="baseline", details=details
        )

    def act(self, decision: Decision, placed: Placed) -> list[ActionRequest]:
        """The folders from the top, the move, then the agent's keyword,
        with the target worked out against the list of now. The keyword
        comes last, so it never stands without the move: the runtime
        records the rest only when a move is recorded only."""
        target = self._target(placed)
        if target is None:
            return []
        paths = from_top(target.path)
        if target.move is None:
            # Below the folder of the owner: it and those above it are there.
            own = placed.own_folder or ""
            paths = tuple(p for p in paths if p.startswith(f"{own}/"))
        requests = [
            ActionRequest(Action.CREATE_FOLDER, placed.ref, folder=path, why="rule")
            for path in paths
        ]
        requests.append(
            ActionRequest(
                Action.MOVE_TO_FOLDER, placed.ref, folder=target.path, why="rule"
            )
        )
        requests.append(
            ActionRequest(Action.ADD_KEYWORD, placed.ref, keyword=self.keyword)
        )
        return requests

    def _target(self, placed: Placed) -> Target | None:
        return self.rules.target(
            placed.keywords, in_inbox=placed.in_inbox, own_folder=placed.own_folder
        )

    # -- what the runtime asks besides ----------------------------------------------

    def may_create(self, path: str, folders: Mapping[str, FolderRef]) -> bool:
        """A folder of a move of the list or one above it, a move with a
        below under it, and a below under a folder of the owner that is
        there, one without a role."""
        if path in self.rules.folders():
            return True
        for below in self.rules.belows():
            parent = path.removesuffix(f"/{below}")
            if parent == path:
                continue
            found = folders.get(parent)
            if found is not None and found.role is None:
                return True
        return False

    def backfill_folder(self, folder: FolderRef) -> bool:
        """A folder of the owner, when a rule of the list files below one."""
        return folder.role is None and bool(self.rules.belows())

    def summarize(self, shown: list[Shown]) -> list[str]:
        """Per rule, as ``rule-<n>``, how many messages were moved, only
        recorded, and left where they were."""
        counted: dict[str, Counter[str]] = {}
        for item in shown:
            label = item.decision.label
            if label == "none":
                continue
            moves = [a for a in item.actions if a.action is Action.MOVE_TO_FOLDER]
            fate = (
                "left"
                if not moves
                else "moved"
                if any(a.done for a in moves)
                else "recorded"
            )
            counted.setdefault(label, Counter())[fate] += 1
        if not counted:
            return []
        lines = ["rules:"]
        for label in sorted(counted, key=lambda name: int(name.split("-")[1])):
            said = ", ".join(
                f"{counted[label][fate]} {fate}"
                for fate in FATES
                if counted[label][fate]
            )
            lines.append(f"  {label}: {said}")
        return lines
