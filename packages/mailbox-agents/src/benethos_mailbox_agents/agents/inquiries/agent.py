"""``inquiries``: is this a project inquiry, and what does it say?

The model labels a message in the inbox ``inquiry`` or ``other``, with a
quote the code finds in the mail, and for an inquiry fills its fields, each
with a quote of its own. A field whose quote is not found is dropped, and
what a message does not say stays empty. An inquiry gets the keyword. The
rules beside it know phrases, dates and rates, and the sender domains and
phrases of a patterns file. See docs/mailbox-agents/concept/agent-inquiries.md.
"""

from __future__ import annotations

from functools import cached_property

from ...contract import (
    Action,
    ActionRequest,
    Agent,
    Context,
    Limits,
    Route,
    Trigger,
)
from ...contract.prompts import load_prompt
from ...records import LABEL, Decision, Event, Evidence, MailMessage
from .baseline import baseline
from .patterns import Patterns, load_patterns
from .schema import FIELDS, Inquiry, parts, render

__all__ = ["Inquiries"]


class Inquiries(Agent):
    name = "inquiries"
    version = "2"
    description = "Marks project inquiries."
    triggers = Trigger(events=frozenset({"message.created"}))
    actions = frozenset({Action.ADD_KEYWORD})
    limits = Limits(model_calls_per_message=1, model_calls_per_day=2000)
    default_keyword = "agent-inquiry"
    report_labels = frozenset({"inquiry", "other"})
    report_fields = frozenset(FIELDS)
    prompt_version = "v4"

    def prepare(self) -> None:
        _ = self.patterns

    @cached_property
    def patterns(self) -> Patterns:
        return load_patterns(self.settings.inquiries_patterns_file)

    @cached_property
    def system(self) -> str:
        fields = "\n".join(f"- `{name}`: {meaning}" for name, meaning in FIELDS.items())
        return load_prompt(__package__ or "", "system", self.prompt_version).replace(
            "{fields}", fields
        )

    def select(self, event: Event) -> Route | None:
        return Route.DECIDE if event.type == "message.created" else None

    def admit(self, message: MailMessage) -> bool:
        return message.in_role("inbox")

    def baseline(self, message: MailMessage) -> Decision:
        return baseline(message, self.patterns)

    async def decide(self, message: MailMessage, context: Context) -> Decision:
        answer = await context.model.ask(
            system=self.system,
            content=render(message),
            evidence=parts(message),
            schema=Inquiry,
        )
        evidence = [Evidence(field=LABEL, value=answer.label, quote=answer.quote)]
        fields: dict[str, str] = {}
        if answer.label == "inquiry":
            for name in FIELDS:
                found = getattr(answer, name)
                if found is not None and found.value.strip() and found.quote:
                    fields[name] = found.value.strip()
                    evidence.append(
                        Evidence(field=name, value=fields[name], quote=found.quote)
                    )
        return Decision(
            label=answer.label,
            source="model",
            fields=fields,
            evidence=tuple(evidence),
        )

    async def effect(
        self, decision: Decision, message: MailMessage, context: Context
    ) -> list[ActionRequest]:
        if decision.label != "inquiry":
            return []
        return [
            ActionRequest(
                Action.ADD_KEYWORD, message.ref, keyword=self.keyword, why="inquiry"
            )
        ]
