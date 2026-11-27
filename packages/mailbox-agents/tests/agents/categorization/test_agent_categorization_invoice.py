"""The recognizer invoice of categorization, the question the agent invoices
asked before it was removed: its rules, its prompt, and a category it holds for:
docs/mailbox-agents/concept/categorization-chain.md."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

from benethos_mailbox_agents.agents.categorization import invoice_rules
from benethos_mailbox_agents.agents.categorization.invoice import Answer, Invoice
from benethos_mailbox_agents.contract import load_prompt
from benethos_mailbox_agents.records import (
    Address,
    Attachment,
    FolderRef,
    MailMessage,
    MessageRef,
)

from .categorization_chain_helpers import QUOTE, Scripted, categorization, decided

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
def test_the_rules_answer_as_those_of_invoices_did(
    found: MailMessage, expected: tuple[str, dict[str, str]]
) -> None:
    """The cases of the rules of the agent invoices, the same answers."""
    decided_by_rules = invoice_rules.baseline(found)

    assert (decided_by_rules.label, decided_by_rules.fields) == expected


def test_the_prompt_is_the_one_invoices_asked_with() -> None:
    """The prompt v5 of the agent invoices, unchanged: a change is a new
    version."""
    ours = load_prompt("benethos_mailbox_agents.agents.categorization", "invoice", "v5")

    assert hashlib.sha256(ours.encode()).hexdigest() == (
        "9ce85b89339bcbc1b2c08e56fb5dcf1f76b0a19cc5da17aba2e4ca32ed5cc58c"
    )
    assert set(Answer.model_fields) == {"label", "near_miss", "quote"}


def test_the_rules_answer_in_the_category_of_the_list(tmp_path: Path) -> None:
    agent = categorization(tmp_path, CHAIN)
    dimension = agent.chain.first

    said = Invoice().rules(dimension, mail("Rechnung 2026-11"))
    other = Invoice().rules(dimension, mail("Mahnung"))

    assert (said.category if said else None) == "Invoice"
    assert other is not None
    assert (other.category, other.details["near_miss"]) == ("none", "reminder")


async def test_an_invoice_of_the_model_holds_with_its_quote(tmp_path: Path) -> None:
    agent = categorization(tmp_path, CHAIN)
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
        load_prompt("benethos_mailbox_agents.agents.categorization", "invoice", "v5")[
            :40
        ]
    )


async def test_a_near_miss_of_the_model_is_none_with_its_kind(tmp_path: Path) -> None:
    agent = categorization(tmp_path, CHAIN)
    model = Scripted({"label": "other", "near_miss": "reminder", "quote": "x"})

    decision = await decided(agent, mail("Mahnung"), model)

    assert (decision.label, decision.details["near_miss"]) == ("none", "reminder")
    assert decision.actionable


async def test_an_invoice_whose_quote_is_not_in_the_mail_is_refused(
    tmp_path: Path,
) -> None:
    agent = categorization(tmp_path, CHAIN)
    model = Scripted(
        {"label": "invoice", "near_miss": "none", "quote": "a sentence the mail lacks"}
    )

    decision = await decided(agent, mail("November"), model)

    assert decision.refused == "evidence"
