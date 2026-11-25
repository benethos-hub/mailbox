"""invoices: the rules alone, readiness, the report and the schema."""

from __future__ import annotations

from typing import get_args

import httpx
import pytest

from benethos_mailbox_agents.agents.invoices.agent import Invoices
from benethos_mailbox_agents.agents.invoices.baseline import NEAR_MISS_WORDS
from benethos_mailbox_agents.agents.invoices.schema import (
    Answer,
    render,
)
from benethos_mailbox_agents.contract import Action
from benethos_mailbox_agents.errors import ConfigError
from benethos_mailbox_agents.evaluation.gold import load_gold
from benethos_mailbox_agents.records import (
    MailMessage,
    MessageRef,
)
from benethos_mailbox_agents.runtime.readiness import readiness, start

from ..agents_fake import ACCOUNT
from ..agents_helpers import (
    Wired,
    mail,
    run,
    settings,
)
from .invoices_helpers import GOLD, MESSAGES, agent, answer

# -- the rules alone ---------------------------------------------------------------


def _message(message_id: str) -> MailMessage:
    raw = MESSAGES[message_id]
    return MailMessage.model_validate(
        {
            "ref": {"account_id": ACCOUNT, "message_id": message_id},
            "subject": raw["subject"],
            "sender": raw["from"],
            "text": raw["text_body"],
            "attachments": [
                {k: a[k] for k in ("filename", "content_type", "size")}
                for a in raw["attachments"]
            ],
        }
    )


def test_the_baseline_on_the_invented_set() -> None:
    rules = agent()
    found = {
        item.message_id: rules.baseline(_message(item.message_id))
        for item in load_gold(GOLD)
    }

    assert {k: (v.label, v.fields) for k, v in found.items()} == {
        "inv-cloudhost": ("invoice", {}),
        "inv-telco-notice": ("invoice", {}),
        "inv-telco-random-sender": ("invoice", {}),
        "inv-unlisted": ("invoice", {}),
        # A receipt that carries its invoice (decided 2026-11-18).
        "inv-platform": ("invoice", {}),
        "near-reminder": ("other", {"near_miss": "reminder"}),
        "near-quote": ("other", {"near_miss": "quotation"}),
        "near-order": ("other", {"near_miss": "order_confirmation"}),
        "near-receipt": ("other", {"near_miss": "payment_receipt"}),
        "plain": ("other", {}),
    }


def _mail(subject: str, text: str = "", pdf: str | None = None) -> MailMessage:
    return MailMessage.model_validate(
        {
            "ref": {"account_id": ACCOUNT, "message_id": "m1"},
            "subject": subject,
            "sender": {"email": "billing@unlisted.example"},
            "text": text,
            "attachments": (
                [{"filename": pdf, "content_type": "application/pdf", "size": 1}]
                if pdf
                else []
            ),
        }
    )


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        # A receipt that carries its invoice, by the file's name or the text.
        (_mail("Your receipt #2210", pdf="Invoice-2210.pdf"), ("invoice", {})),
        (
            _mail("Zahlungsbestätigung", "Die Rechnung liegt bei.", pdf="Beleg.pdf"),
            ("invoice", {}),
        ),
        # A receipt alone is the near miss.
        (
            _mail("Your receipt #2210", "Thanks for your payment."),
            ("other", {"near_miss": "payment_receipt"}),
        ),
        (
            _mail("Quittung Nr. 7", pdf="Quittung-7.pdf"),
            ("other", {"near_miss": "payment_receipt"}),
        ),
        # A reminder stays a reminder, its invoice attached or not.
        (
            _mail("Mahnung", pdf="Rechnung-1.pdf"),
            ("other", {"near_miss": "reminder"}),
        ),
        # The sender plays no part: a PDF alone is no invoice.
        (_mail("Unterlagen", pdf="Scan.pdf"), ("other", {})),
    ],
    ids=[
        "receipt-invoice-file",
        "receipt-invoice-text",
        "receipt",
        "quittung",
        "reminder",
        "pdf-alone",
    ],
)
def test_the_rules_tell_a_receipt_with_its_invoice(
    message: MailMessage, expected: tuple[str, dict[str, str]]
) -> None:
    found = agent().baseline(message)

    assert (found.label, found.fields) == expected


@pytest.mark.parametrize(
    "text",
    [
        "Ihre Rechnung ist da und liegt im Kundencenter.",
        "Ihre Rechnung wurde bereitgestellt.",
        "Die Monatsrechnung für Oktober finden Sie online.",
        "Your bill is ready to view.",
        "Your statement is available in your account.",
    ],
)
def test_the_rules_take_a_notice_that_an_invoice_waits(text: str) -> None:
    found = agent().baseline(_mail("Neuigkeiten zu Ihrem Konto", text))

    assert found.label == "invoice"


def test_the_content_names_sender_subject_and_files() -> None:
    content = render(_message("inv-cloudhost"))

    assert content.startswith("From: billing@cloudhost.example\nSubject: Ihre Rechnung")
    assert "Attachments: R-2026-1101.pdf (application/pdf)" in content


def test_the_prompt_names_no_supplier() -> None:
    system = agent().system

    assert "supplier`" not in system
    assert "{suppliers}" not in system
    assert "is it an invoice?" in system


def test_a_receipt_that_carries_its_invoice_is_an_invoice_to_the_model() -> None:
    """The owner's receipts carry the invoice (decided 2026-11-18): only a
    payment confirmation without one is the near miss."""
    system = agent().system

    assert "a receipt or payment confirmation that carries the invoice" in system
    assert "with no\n  invoice attached" in system


def test_a_credit_note_is_an_invoice_to_the_model_and_the_rules() -> None:
    """A credit note books like an invoice (decided 2026-11-18)."""
    assert 'a credit note from a supplier, a "Gutschrift"' in agent().system
    for message in (
        _mail("Ihre Gutschrift Nr. 88", pdf="GS-88.pdf"),
        _mail("Credit note CN-12"),
    ):
        assert agent().baseline(message).label == "invoice"


# -- readiness ---------------------------------------------------------------------

READY = {
    "service_url": "https://mailbox.example.test",
    "service_token": "t",
    "gateway_url": "https://gateway.example.test/v1",
    "gateway_key": "k",
}


def test_it_needs_no_setting_of_its_own() -> None:
    assert readiness(Invoices, settings(**READY)).ready


def test_a_wrong_folder_setting_stops_the_start() -> None:
    values = settings(**READY, invoices_subfolder="Rechnungen")

    assert "INVOICES_SUBFOLDER" in (readiness(Invoices, values).problem or "")
    with pytest.raises(ConfigError, match="^invoices is not ready: "):
        start(Invoices, values)


def test_the_keyword_of_another_agent_stops_the_start() -> None:
    """Set in settings several agents share, the keyword setting gives
    them one keyword, and invoices would skip what categorization marked."""
    values = settings(**READY, keyword="agent-categorized")

    assert "of categorization" in (readiness(Invoices, values).problem or "")
    with pytest.raises(ConfigError, match="own env file"):
        start(Invoices, values)
    assert readiness(Invoices, settings(**READY, keyword="agent-invoice")).ready
    assert readiness(Invoices, settings(**READY, keyword="agent-bills")).ready


def test_the_folders_it_expects() -> None:
    found = agent(invoices_folders=["Invoices/*", "Archive"], invoices_inbox_folder="X")

    assert found.folders_needed() == ("Archive", "Invoices", "X")


async def test_a_gateway_that_is_away_leaves_the_invoice_pending(
    invoices_world: Wired,
) -> None:
    invoices_world.fake_gateway.answer(httpx.Response(503))

    assert await run(invoices_world, "inv-cloudhost", agent()) == "pending"

    row = invoices_world.store.message(
        MessageRef(account_id=ACCOUNT, message_id="inv-cloudhost")
    )
    assert row is not None and row.attempts == 0
    assert mail(invoices_world, "inv-cloudhost")["keywords"] == []


# -- the report --------------------------------------------------------------------


async def test_the_report_names_invoices_marked_and_not_moved(
    invoices_world: Wired,
) -> None:
    from benethos_mailbox_agents.cli.report import collect, render, summary

    invoices_world.fake_gateway.answer(
        answer("invoice", "please find attached invoice INV-77"),
        answer("invoice", "Ihre Rechnung R-77"),
    )
    await run(invoices_world, "inv-unlisted", agent())
    await run(invoices_world, "filed", agent())

    entries = await collect(invoices_world.store, invoices_world.mailbox, limit=10)
    lines = render(entries) + summary(agent(), entries)

    assert lines[-2:] == [
        "invoices marked and not moved, by sender:",
        "  accounts@paperworks.example (1 invoice)",
    ]


def test_summarize_counts_invoices_left_where_they_lay() -> None:
    from benethos_mailbox_agents.contract import Shown, ShownAction
    from benethos_mailbox_agents.records import Decision

    invoice = Decision(label="invoice", source="model")
    refused = invoice.model_copy(update={"refused": "evidence"})
    other = Decision(label="other", source="model")
    marked = (ShownAction(Action.ADD_KEYWORD, True),)
    moved = (
        ShownAction(Action.ADD_KEYWORD, True),
        ShownAction(Action.MOVE_TO_FOLDER, True),
    )
    recorded = (
        ShownAction(Action.ADD_KEYWORD, False),
        ShownAction(Action.MOVE_TO_FOLDER, False),
    )

    lines = agent().summarize(
        [
            Shown("accounts@paperworks.example", invoice, marked),
            Shown("Accounts@Paperworks.example", invoice, marked),
            Shown("billing@new.example", invoice, ()),
            Shown("rechnung@telco.example", invoice, moved),
            Shown("billing@host.example", invoice, recorded),
            Shown("x@refused.example", refused, ()),
            Shown("y@other.example", other, ()),
            Shown(None, invoice, ()),
        ]
    )

    assert lines == [
        "invoices marked and not moved, by sender:",
        "  accounts@paperworks.example (2 invoices)",
        "  billing@new.example (1 invoice)",
    ]
    assert agent().summarize([Shown("y@other.example", other)]) == []


# -- the schema ----------------------------------------------------------------------


def test_the_near_misses_of_the_rules_are_those_of_the_schema() -> None:
    """The near misses stand in the rules and in the schema: a new one in
    either must come to the other."""
    named = get_args(Answer.model_fields["near_miss"].annotation)

    assert set(NEAR_MISS_WORDS) | {"none"} == set(named)


async def test_a_long_quote_is_refused_as_schema(invoices_world: Wired) -> None:
    invoices_world.fake_gateway.answer(answer("invoice", "y" * 1000))

    assert await run(invoices_world, "inv-cloudhost", agent()) == "pending"

    assert mail(invoices_world, "inv-cloudhost")["keywords"] == []
