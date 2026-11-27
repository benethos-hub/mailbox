"""The agent that only counts.

Every message created or sent becomes ``pending``, runs the steps and ends
``done`` with the label ``counted``, without a model call and without an
action. So the feed, the state file, the steps, the report and the health
of a deployment can be checked before any agent may change a message.
"""

from __future__ import annotations

from ...contract import (
    Action,
    ActionRequest,
    Classifier,
    Context,
    Limits,
    Route,
    Trigger,
)
from ...records import Decision, MailMessage

__all__ = ["Counting"]


class Counting(Classifier):
    name = "counting"
    version = "1"
    description = "Counts the messages that arrive or are sent. No model, no action."
    triggers = Trigger(
        routes={"message.created": Route.DECIDE, "message.sent": Route.DECIDE}
    )
    actions = frozenset[Action]()
    limits = Limits(model_calls_per_message=0, model_calls_per_day=0)
    default_keyword = "agent-counted"
    report_labels = frozenset({"counted"})

    def baseline(self, message: MailMessage) -> Decision:
        roles = sorted({f.role for f in message.folders if f.role})
        return Decision(
            label="counted",
            source="baseline",
            details={"roles": ",".join(roles)},
        )

    async def decide(self, message: MailMessage, context: Context) -> Decision:
        return self.baseline(message)

    async def effect(
        self, decision: Decision, message: MailMessage, context: Context
    ) -> list[ActionRequest]:
        return []
