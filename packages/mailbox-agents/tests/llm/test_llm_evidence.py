"""The evidence check of docs/mailbox-agents/concept/safety.md."""

from __future__ import annotations

import unicodedata

import pytest

from benethos_mailbox_agents.agents.invoices.schema import parts, render
from benethos_mailbox_agents.llm.evidence import check, contains
from benethos_mailbox_agents.records import (
    LABEL,
    Address,
    Attachment,
    Decision,
    Evidence,
    MailMessage,
    MessageRef,
)

NBSP = chr(0xA0)

TEXT = (
    "Sehr geehrte Damen und Herren,\n\n"
    f"anbei  die\tRechnung{NBSP}Nr. 4711 vom 01.11.2026."
)
CONTENT = f"Subject: Ihre Rechnung\n\n{TEXT}"

# The same mail as the parts the model was given, without the frame.
PARTS = ("CloudHost <billing@cloudhost.example>", "Ihre Rechnung", TEXT)


@pytest.mark.parametrize(
    ("quote", "found"),
    [
        ("anbei die Rechnung Nr. 4711", True),
        ("anbei\ndie   Rechnung", True),
        ("  Ihre Rechnung  ", True),
        ("ihre rechnung", True),
        ("Rechnung Nr 4711", True),
        ("„anbei die Rechnung“ – Nr. 4711", True),
        ("Subject: Ihre Rechnung", True),
        ("anbei eine Rechnung", False),
        ("anbei Rechnung Nr. 4711", False),
        ("Rechnung Nr. 4712", False),
        ("", False),
        ("   ", False),
        ("Nr. 4711", False),
        ("Rechnung Nr. 4711", True),
    ],
)
def test_a_quote_is_looked_up(quote: str, found: bool) -> None:
    assert contains(CONTENT, quote) is found


def _decision(*evidence: Evidence, **fields: str) -> Decision:
    return Decision(label="invoice", source="model", fields=fields, evidence=evidence)


def test_a_found_label_and_field_stay() -> None:
    decided = check(
        _decision(
            Evidence(field=LABEL, value="invoice", quote="Ihre Rechnung"),
            Evidence(field="number", value="4711", quote="Rechnung Nr. 4711"),
            number="4711",
        ),
        PARTS,
    )

    assert decided.actionable
    assert decided.fields == {"number": "4711"}
    assert all(item.found for item in decided.evidence)


def test_a_field_whose_quote_is_not_found_is_dropped() -> None:
    decided = check(
        _decision(
            Evidence(field=LABEL, value="invoice", quote="Ihre Rechnung"),
            Evidence(field="number", value="9999", quote="Rechnung Nr. 9999"),
            number="9999",
        ),
        PARTS,
    )

    assert decided.actionable
    assert decided.fields == {}
    assert [item.found for item in decided.evidence] == [True, False]


def test_a_field_without_a_quote_is_dropped() -> None:
    label = Evidence(field=LABEL, value="invoice", quote="Ihre Rechnung")

    decided = check(_decision(label, date="x"), PARTS)

    assert decided.fields == {}


def test_a_label_whose_quote_is_not_found_is_refused() -> None:
    decided = check(
        _decision(Evidence(field=LABEL, value="invoice", quote="Your invoice")),
        PARTS,
    )

    assert decided.refused == "evidence"
    assert not decided.actionable


def test_a_label_without_any_quote_is_refused() -> None:
    assert check(_decision(), PARTS).refused == "evidence"


def test_a_value_found_by_a_rule_stays_found() -> None:
    label = Evidence(field=LABEL, value="invoice", quote="Ihre Rechnung")
    rule = Evidence(field="supplier", value="CloudHost", quote="", found=True)

    decided = check(_decision(label, rule, supplier="CloudHost"), PARTS)

    assert decided.fields == {"supplier": "CloudHost"}


def test_an_earlier_refusal_is_kept() -> None:
    decided = _decision(
        Evidence(field=LABEL, value="invoice", quote="Ihre Rechnung")
    ).model_copy(update={"refused": "limit"})

    assert check(decided, PARTS).refused == "limit"


def _invoice() -> MailMessage:
    return MailMessage(
        ref=MessageRef(account_id="acc1", message_id="m1"),
        subject="Ihre Rechnung R-1",
        sender=Address(email="billing@cloudhost.example", name="CloudHost"),
        text="Sehr geehrte Kundin, anbei Ihre Rechnung.",
        attachments=(
            Attachment(filename="R-1.pdf", content_type="application/pdf", size=1),
        ),
    )


@pytest.mark.parametrize("quote", ["Subject:", "From:", "Attachments:", ":", "e"])
def test_the_frame_and_a_short_quote_back_nothing(quote: str) -> None:
    message = _invoice()
    label = Evidence(field=LABEL, value="invoice", quote=quote)

    assert quote in render(message)
    assert check(_decision(label), parts(message)).refused == "evidence"


@pytest.mark.parametrize(
    "quote", ["anbei Ihre Rechnung.", "Ihre Rechnung R-1", "CloudHost <billing@"]
)
def test_a_passage_of_the_mail_backs_the_label(quote: str) -> None:
    label = Evidence(field=LABEL, value="invoice", quote=quote)

    assert check(_decision(label), parts(_invoice())).actionable


@pytest.mark.parametrize(
    ("quote", "found"),
    [
        ("We’ve updated the Terms", True),
        ("we've updated the terms", True),
        ("Jobs: * lint / Dockerfile lint failed", True),
        ("Jobs lint Dockerfile lint failed", True),
        ("We have updated the Terms", False),
    ],
)
def test_marks_and_case_are_forgiven_words_are_not(quote: str, found: bool) -> None:
    """The kinds of difference the shadow run of 2026-11-18 refused for: a
    typographic apostrophe, the case of a word, the marks between words."""
    content = "We've updated the Terms.\n\nJobs:\n* lint / Dockerfile-lint failed"

    assert contains(content, quote) is found


@pytest.mark.parametrize(
    ("quote", "found"),
    [
        ("voice number 1234", False),
        ("invoice number 1234", False),
        ("voice number 12345", False),
        ("invoice number 12345", True),
        ("Please pay invoice number 12345 today", True),
    ],
)
def test_a_word_cut_short_at_either_end_is_not_found(quote: str, found: bool) -> None:
    assert contains("Please pay invoice number 12345 today", quote) is found


def test_letters_and_digits_count_for_the_shortest_quote() -> None:
    assert not contains("R.-Nr.: 4711", "R.-Nr.: 4711")
    assert contains("Rechnung 4711", "Rechnung 4711")


def test_a_quote_does_not_span_two_parts() -> None:
    label = Evidence(field=LABEL, value="invoice", quote="Rechnung Sehr geehrte")

    assert check(_decision(label), PARTS).refused == "evidence"


def test_decomposed_text_and_a_composed_quote_match() -> None:
    text = unicodedata.normalize("NFD", "Rechnung für Müller")

    assert text != "Rechnung für Müller"
    assert contains(text, "Rechnung für Müller")
    assert contains("Rechnung für Müller", text)
