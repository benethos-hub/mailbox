"""The agent ``forwarding``: an actor that drafts a forward of mail with
certain keywords, by a list its owner wrote. It sends nothing.

A message is taken up once it carries a keyword the list waits for. The
first rule that fits gives the addresses and the form, and the forward is
put into the drafts folder of the account, once per message, at most 20
a day. It is only recorded when the sender check of the message failed,
or did not pass and the rule asks for it, and nothing is drafted for a
message that came from an address of the rule. No model, and nothing of
what a mail says: the agent sees it as ``Placed``. It sets no keyword: its
state file holds that a message was forwarded. See
docs/mailbox-agents/concept/agent-forwarding.md.
"""

from __future__ import annotations

from collections import Counter
from functools import cached_property

from ...contract import (
    Action,
    ActionRequest,
    Actor,
    Limits,
    Placed,
    Requires,
    Shown,
    list_version,
)
from ...errors import ConfigError
from ...records import Decision
from ...settings import PREFIX
from .rules import Rule, Rules, load_rules

__all__ = ["Forwarding"]

# What became of the messages of a rule, in the order a report names it.
FATES = ("drafted", "recorded", "left")


class Forwarding(Actor):
    name = "forwarding"
    version = "1"
    description = (
        "Drafts a forward of mail by its keywords, by a list. Sends nothing, "
        "no model, nothing of what a mail says."
    )
    actions = frozenset({Action.DRAFT_FORWARD})
    limits = Limits(model_calls_per_message=0, model_calls_per_day=0, drafts_per_day=20)
    requires = Requires(settings=("forwarding_file",))
    # Declared and never set: the state file holds what was forwarded.
    default_keyword = "agent-forwarded"

    # -- what it reads besides its settings -----------------------------------

    def prepare(self) -> None:
        """Read the list now, so a wrong one stops the start."""
        _ = self.rules

    @cached_property
    def rules(self) -> Rules:
        """The list, read once. Its digest is the version of a decision, so
        a changed list is new work."""
        path = self.settings.forwarding_file
        if path is None:
            raise ConfigError(f"{PREFIX}FORWARDING_FILE is not set")
        found = load_rules(path)
        self.prompt_version = "v1-" + list_version(found)
        return found

    # -- the actor ------------------------------------------------------------------

    def waits_for(self, keyword: str) -> bool:
        return self.rules.waits_for(keyword)

    def recipients(self) -> frozenset[str]:
        """Every address of the list, and no other."""
        return self.rules.recipients()

    def rule(self, placed: Placed) -> Decision:
        """The first rule that fits, as ``rule-<n>``, else none. The
        details say why nothing would be drafted, as a code, never an
        address."""
        found = self.rules.first(placed.keywords)
        if found is None:
            return Decision(label="none", source="baseline")
        place, rule = found
        return Decision(
            label=f"rule-{place}",
            source="baseline",
            details={"why": _why(rule, placed)},
        )

    def act(self, decision: Decision, placed: Placed) -> list[ActionRequest]:
        """A draft of a forward by the first rule of the list of now: none
        for a message from an address of the rule, recorded only when its
        sender check does not allow it (decided 2026-11-27)."""
        found = self.rules.first(placed.keywords)
        if found is None:
            return []
        rule = found[1]
        why = _why(rule, placed)
        if why == "from-recipient":
            return []
        return [
            ActionRequest(
                Action.DRAFT_FORWARD,
                placed.ref,
                recipients=rule.to,
                forward_as=rule.forward_as,
                why="rule",
                held=why == "sender-check",
            )
        ]

    def summarize(self, shown: list[Shown]) -> list[str]:
        """Per rule, as ``rule-<n>``, how many forwards were drafted, only
        recorded, and left without one."""
        counted: dict[str, Counter[str]] = {}
        for item in shown:
            label = item.decision.label
            if label == "none":
                continue
            asked = [a for a in item.actions if a.action is Action.DRAFT_FORWARD]
            fate = (
                "left"
                if not asked
                else "drafted"
                if any(a.done for a in asked)
                else "recorded"
            )
            counted.setdefault(label, Counter())[fate] += 1
        if not counted:
            return []
        lines = ["rules:"]
        for label in sorted(counted, key=lambda name: int(name.split("-")[1])):
            fates = counted[label]
            said = ", ".join(f"{fates[fate]} {fate}" for fate in FATES if fates[fate])
            lines.append(f"  {label}: {said}")
        return lines


def _why(rule: Rule, placed: Placed) -> str:
    """Whether a forward follows: ``from-recipient`` for a message that
    came from an address of the rule, which would go back in a loop,
    ``sender-check`` when its check failed or did not pass and the rule
    asks for it, else ``forward``."""
    if placed.sent_by(rule.to):
        return "from-recipient"
    if placed.sender_check == "fail":
        return "sender-check"
    if placed.sender_check != "pass" and rule.sender_check == "required":
        return "sender-check"
    return "forward"
