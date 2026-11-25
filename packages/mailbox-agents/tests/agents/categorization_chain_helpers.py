"""What the tests of the chain of categorization share: a list of dimensions, a
message in the inbox, and a model that answers from a script."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, TypeVar, cast

from pydantic import BaseModel

from benethos_mailbox_agents.agents.categorization.agent import Categorization
from benethos_mailbox_agents.contract import Context
from benethos_mailbox_agents.errors import LimitReachedError
from benethos_mailbox_agents.llm.evidence import check
from benethos_mailbox_agents.records import (
    Address,
    Decision,
    FolderRef,
    MailMessage,
    MessageRef,
)

from ..agents_helpers import settings

T = TypeVar("T", bound=BaseModel)

INBOX = FolderRef(id="inbox", name="Inbox", role="inbox", path="Inbox")

INVOICE = "Invoices of a provider for a service the owner pays"
NOTICE = "Notices of a provider about a change of its terms"
QUOTE = "please find attached the invoice for November"

CHAIN: dict[str, Any] = {
    "dimensions": [
        {
            "name": "partner",
            "categories": [
                {
                    "name": "Bank",
                    "senders": ["*@bank.example"],
                    "then": [{"move": "Providers/Bank"}, {"keyword": "agent-bank"}],
                },
                {
                    "name": "Hosting",
                    "senders": ["*@hosting.example"],
                    "then": [{"move": "Providers/Hosting"}],
                },
            ],
        },
        {
            "name": "kind",
            "when": {"partner": ["Bank", "Hosting"]},
            "categories": [
                {
                    "name": "Invoice",
                    "topic": INVOICE,
                    "by_topic": "act",
                    "then": [
                        {"move_below": "Invoices"},
                        {"keyword": "agent-invoice"},
                    ],
                },
                {
                    "name": "Notice",
                    "topic": NOTICE,
                    "then": [{"keyword": "agent-notice"}],
                },
            ],
        },
    ]
}


def written(tmp_path: Path, chain: dict[str, Any] | None = None) -> Path:
    path = tmp_path / "categorization.json"
    path.write_text(json.dumps(CHAIN if chain is None else chain), encoding="utf-8")
    return path


def categorization(
    tmp_path: Path, chain: dict[str, Any] | None = None, stage: str = "full"
) -> Categorization:
    found = Categorization(
        settings(stage=stage, categorization_file=written(tmp_path, chain))
    )
    found.prepare()
    return found


def message(
    sender: str,
    *,
    text: str = f"Hello,\n{QUOTE}.\n",
    folders: Sequence[FolderRef] = (INBOX,),
    keywords: Sequence[str] = (),
    message_id: str = "m1",
) -> MailMessage:
    return MailMessage(
        ref=MessageRef(account_id="acc1", message_id=message_id),
        folders=tuple(folders),
        sender=Address(email=sender),
        subject="November",
        text=text,
        keywords=tuple(keywords),
    )


class Scripted:
    """A model that answers from a script, at most ``limit`` times, and
    keeps the parts of the mail for the evidence check."""

    def __init__(self, *answers: dict[str, str], limit: int = 2) -> None:
        self.answers = list(answers)
        self.asked: list[str] = []
        self.parts: list[str] = []
        self.limit = limit

    async def ask(
        self, *, system: str, content: str, schema: type[T], evidence: Sequence[str]
    ) -> T:
        if len(self.asked) >= self.limit:
            raise LimitReachedError("more calls than allowed", per_day=False)
        self.asked.append(system)
        self.parts.extend(evidence)
        return schema.model_validate(self.answers.pop(0))


def context(model: Scripted) -> Context:
    return Context(
        model=model,
        reader=cast(Any, None),
        items=cast(Any, None),
        now=lambda: datetime(2026, 11, 25),
    )


async def decided(
    agent: Categorization, found: MailMessage, model: Scripted
) -> Decision:
    """The decision as the runtime checks it."""
    decision = await agent.decide(found, context(model))
    if decision.source == "model":
        decision = check(decision, model.parts)
    return decision
