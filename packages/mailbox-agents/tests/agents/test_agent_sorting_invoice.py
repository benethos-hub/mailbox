"""The recognizer invoice of sorting, a copy of the question of the agent
invoices: its rules, its prompt, and a category it holds for:
docs/mailbox-agents/concept/sorting-chain.md."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from benethos_mailbox_agents.agents.sorting import invoice_rules
from benethos_mailbox_agents.agents.sorting.invoice import Answer, Invoice
from benethos_mailbox_agents.contract import load_prompt
from benethos_mailbox_agents.records import (
    Address,
    Attachment,
    FolderRef,
    MailMessage,
    MessageRef,
)

from ..agents_helpers import ROOT
from .sorting_chain_helpers import QUOTE, Scripted, decided, sorting

INBOX = FolderRef(id="inbox", name="Inbox", role="inbox", path="Inbox")

CHAIN: dict[str, Any] = {
    "dimensions": [
        {
            "name": "kind",
            "categories": [
                {
                    "name": "Invoice",
                    "recognize": "invoice",
                    "then": [{"keyword": "agent-invoice"}],
                }
            ],
        }
    ]
}


def mail(subject: str, text: str = "Hello.", pdf: str | None = None) -> MailMessage:
    files = (
        (Attachment(filename=pdf, content_type="application/pdf", size=10),)
        if pdf
        else ()
    )
    return MailMessage(
        ref=MessageRef(account_id="acc1", message_id="m1"),
        folders=(INBOX,),
        sender=Address(email="billing@cloudhost.example"),
        subject=subject,
        text=text,
        attachments=files,
    )


CASES = [
    (mail("Your receipt #2210", pdf="Invoice-2210.pdf"), ("invoice", {})),
    (
        mail("Zahlungsbestätigung", "Die Rechnung liegt bei.", pdf="Beleg.pdf"),
        ("invoice", {}),
    ),
    (
        mail("Your receipt #2210", "Thanks for your payment."),
        ("other", {"near_miss": "payment_receipt"}),
    ),
    (
        mail("Quittung Nr. 7", pdf="Quittung-7.pdf"),
        ("other", {"near_miss": "payment_receipt"}),
    ),
    (mail("Mahnung", pdf="Rechnung-1.pdf"), ("other", {"near_miss": "reminder"})),
    (mail("Unterlagen", pdf="Scan.pdf"), ("other", {})),
    (
        mail("Neuigkeiten", "Ihre Rechnung ist da und liegt im Kundencenter."),
        ("invoice", {}),
    ),
    (mail("Your bill", "Your bill is ready to view."), ("invoice", {})),
]


@pytest.mark.parametrize(
    ("found", "expected"), CASES, ids=[m.subject or "" for m, _ in CASES]
)
def test_the_rules_answer_as_those_of_invoices(
    found: MailMessage, expected: tuple[str, dict[str, str]]
) -> None:
    """The cases of the rules of the agent invoices, the same answers."""
    decided_by_rules = invoice_rules.baseline(found)

    assert (decided_by_rules.label, decided_by_rules.fields) == expected


def test_the_prompt_is_a_copy_of_the_one_of_invoices() -> None:
    ours = load_prompt("benethos_mailbox_agents.agents.sorting", "invoice", "v5")
    theirs = ROOT / (
        "packages/mailbox-agents/src/benethos_mailbox_agents/agents/invoices/"
        "prompts/system.v5.md"
    )

    assert ours == theirs.read_text(encoding="utf-8")
    assert set(Answer.model_fields) == {"label", "near_miss", "quote"}


def test_the_rules_answer_in_the_category_of_the_list(tmp_path: Path) -> None:
    agent = sorting(tmp_path, CHAIN)
    dimension = agent.chain.first

    said = Invoice().rules(dimension, mail("Rechnung 2026-11"))
    other = Invoice().rules(dimension, mail("Mahnung"))

    assert (said.category if said else None) == "Invoice"
    assert other is not None
    assert (other.category, other.details["near_miss"]) == ("none", "reminder")


async def test_an_invoice_of_the_model_holds_with_its_quote(tmp_path: Path) -> None:
    agent = sorting(tmp_path, CHAIN)
    model = Scripted({"label": "invoice", "near_miss": "none", "quote": QUOTE})
    found = mail("November", f"Hello,\n{QUOTE}.\n")

    decision = await decided(agent, found, model)

    assert (decision.label, decision.source, decision.actionable) == (
        "Invoice",
        "model",
        True,
    )
    assert decision.details["match"] == "invoice"
    assert agent.prompt_version.endswith("-invoice-v5")
    assert model.asked[0].startswith(
        load_prompt("benethos_mailbox_agents.agents.sorting", "invoice", "v5")[:40]
    )


async def test_a_near_miss_of_the_model_is_none_with_its_kind(tmp_path: Path) -> None:
    agent = sorting(tmp_path, CHAIN)
    model = Scripted({"label": "other", "near_miss": "reminder", "quote": "x"})

    decision = await decided(agent, mail("Mahnung"), model)

    assert (decision.label, decision.details["near_miss"]) == ("none", "reminder")
    assert decision.actionable


async def test_an_invoice_whose_quote_is_not_in_the_mail_is_refused(
    tmp_path: Path,
) -> None:
    agent = sorting(tmp_path, CHAIN)
    model = Scripted(
        {"label": "invoice", "near_miss": "none", "quote": "a sentence the mail lacks"}
    )

    decision = await decided(agent, mail("November"), model)

    assert decision.refused == "evidence"
