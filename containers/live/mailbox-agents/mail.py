"""The invented mail of the live setup. Every name, address and number is
made up, and every domain is one reserved for examples (RFC 2606).

``messages`` yields each message with the folder it goes into, by role
(``inbox``, ``sent``) or by name, and its IMAP flags.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from email.utils import format_datetime

__all__ = ["FOLDERS", "GOLD", "SUB_FOLDERS", "local", "messages"]

# A folder at the top and two below it, for the checks of the folders.
SUB_FOLDERS = ("Invoices/CloudHost", "Invoices/Telco")
FOLDERS = ("Invoices", *SUB_FOLDERS)

NOW = datetime.now(UTC).replace(microsecond=0)
PDF = b"%PDF-1.4\n% invented, not a real document\n%%EOF\n"


def _message(
    *,
    sender: str,
    to: str,
    subject: str,
    body: str,
    days_ago: float,
    message_id: str,
    pdf: str | None = None,
    reply_to: str | None = None,
    headers: dict[str, str] | None = None,
) -> EmailMessage:
    found = EmailMessage()
    found["From"] = sender
    found["To"] = to
    found["Subject"] = subject
    found["Date"] = format_datetime(NOW - timedelta(days=days_ago))
    found["Message-ID"] = f"<{message_id}@invented.example>"
    if reply_to:
        found["In-Reply-To"] = f"<{reply_to}@invented.example>"
        found["References"] = f"<{reply_to}@invented.example>"
    for name, value in (headers or {}).items():
        found[name] = value
    found.set_content(body)
    if pdf:
        found.add_attachment(PDF, maintype="application", subtype="pdf", filename=pdf)
    return found


def local(header: str | None) -> str:
    """The part of a Message-ID before the @, without its brackets: the
    name each message of :func:`messages` carries, as GOLD keys it."""
    return (header or "").strip("<>").partition("@")[0]


def messages(me: str) -> Iterator[tuple[str, str, EmailMessage]]:
    """Folder, flags and message of every invented message."""
    inbox, sent, seen = "inbox", "sent", r"(\Seen)"

    # --- invoices: with and without a PDF, filed by their provider
    yield (
        inbox,
        "",
        _message(
            sender="CloudHost Billing <billing@cloudhost.example>",
            to=me,
            subject="Ihre Rechnung R-2026-1101",
            body="Guten Tag,\n\nanbei erhalten Sie Ihre Rechnung R-2026-1101 "
            "über 12,40 EUR für November.\n\nIhr CloudHost-Team",
            days_ago=2,
            message_id="inv-cloudhost-1",
            pdf="R-2026-1101.pdf",
        ),
    )
    yield (
        inbox,
        "",
        _message(
            sender="Telco Kundenservice <rechnung@telco.example>",
            to=me,
            subject="Ihre Rechnung für November ist online",
            body="Hallo,\n\nIhre Rechnung für November steht ab sofort im "
            "Kundenportal zum Abruf bereit.\n\nIhr Telco-Team",
            days_ago=2,
            message_id="inv-telco-1",
        ),
    )
    yield (
        inbox,
        "",
        _message(
            sender="Paperworks Accounts <accounts@paperworks.example>",
            to=me,
            subject="Invoice INV-77",
            body="Hello,\n\nplease find attached invoice INV-77 for the paper "
            "you ordered.\n\nKind regards,\nPaperworks",
            days_ago=1,
            message_id="inv-paperworks-1",
            pdf="INV-77.pdf",
        ),
    )
    # A receipt that carries the invoice: an invoice, not a payment receipt.
    yield (
        inbox,
        "",
        _message(
            sender="Platform Billing <billing@platform.example>",
            to=me,
            subject="Your receipt from Platform Billing #2210-4471",
            body="Thank you for your payment of 21.42 EUR for your Platform "
            "subscription.\n\nThe invoice for this payment is attached.\n\n"
            "Platform Billing",
            days_ago=1,
            message_id="inv-receipt-1",
            pdf="Invoice-2210-4471.pdf",
        ),
    )

    # --- near misses
    yield (
        inbox,
        "",
        _message(
            sender="CloudHost Billing <billing@cloudhost.example>",
            to=me,
            subject="Zahlungserinnerung zu R-2026-1001",
            body="Guten Tag,\n\nzu unserer Rechnung R-2026-1001 konnten wir noch "
            "keinen Zahlungseingang feststellen. Bitte überweisen Sie den "
            "Betrag bis zum Monatsende.\n\nIhr CloudHost-Team",
            days_ago=3,
            message_id="near-reminder-1",
        ),
    )
    yield (
        inbox,
        "",
        _message(
            sender="Paperworks Sales <sales@paperworks.example>",
            to=me,
            subject="Angebot Nr. 5521",
            body="Guten Tag,\n\nwie besprochen erhalten Sie unser Angebot "
            "Nr. 5521 für 500 Blatt Papier.\n\nPaperworks",
            days_ago=4,
            message_id="near-quote-1",
            pdf="Angebot-5521.pdf",
        ),
    )
    yield (
        inbox,
        seen,
        _message(
            sender="Shop <orders@shop.example>",
            to=me,
            subject="Ihre Bestellung 4711 ist bestätigt",
            body="Danke für Ihre Bestellung 4711. Sie wird in zwei Tagen versandt.",
            days_ago=5,
            message_id="near-order-1",
        ),
    )
    yield (
        inbox,
        seen,
        _message(
            sender="CloudHost Billing <billing@cloudhost.example>",
            to=me,
            subject="Zahlungseingang bestätigt",
            body="Wir haben Ihre Zahlung zu R-2026-1001 erhalten. Vielen Dank.",
            days_ago=6,
            message_id="near-receipt-1",
        ),
    )

    # --- a project inquiry and a newsletter
    yield (
        inbox,
        "",
        _message(
            sender="Jana Example <jana@staffing.example>",
            to=me,
            subject="Projektanfrage: Python-Entwicklung, remote",
            body="Hallo,\n\nfür einen Kunden aus der Logistik suchen wir ab "
            "01.02.2027 für 6 Monate Unterstützung in der Python-Entwicklung, "
            "Auslastung 4 Tage pro Woche, 80 % remote, Einsatzort Hamburg. "
            "Stundensatz bis 95 EUR. Wichtig sind FastAPI und PostgreSQL, "
            "Kubernetes wäre schön. Bewerbungen bitte bis 15.12.2026.\n\n"
            "Viele Grüße\nJana",
            days_ago=1,
            message_id="inquiry-1",
        ),
    )
    yield (
        inbox,
        seen,
        _message(
            sender="News <news@newsletter.example>",
            to=me,
            subject="Die Neuigkeiten der Woche",
            body="Diese Woche: drei Tipps für ein aufgeräumtes Postfach.",
            days_ago=2,
            message_id="newsletter-1",
            headers={"List-Unsubscribe": "<mailto:leave@newsletter.example>"},
        ),
    )

    # --- sent mail that waits for a reply, one answered, one not, one not
    # asking anything, and an automatic answer
    yield (
        sent,
        seen,
        _message(
            sender=me,
            to="Partner <partner@partner.example>",
            subject="Angebot für das Projekt",
            body="Hallo,\n\nkönnten Sie mir bis Freitag Ihr Angebot schicken?\n\n"
            "Viele Grüße",
            days_ago=6,
            message_id="sent-asked-answered",
        ),
    )
    yield (
        inbox,
        "",
        _message(
            sender="Partner <partner@partner.example>",
            to=me,
            subject="Re: Angebot für das Projekt",
            body="Hallo,\n\ngern, das Angebot kommt morgen.\n\nGrüße",
            days_ago=5,
            message_id="reply-partner",
            reply_to="sent-asked-answered",
        ),
    )
    yield (
        sent,
        seen,
        _message(
            sender=me,
            to="Office <office@client.example>",
            subject="Rückfrage zur Rechnung",
            body="Guten Tag,\n\nbitte teilen Sie mir mit, an welche Adresse die "
            "Rechnung gehen soll.\n\nDanke",
            days_ago=8,
            message_id="sent-asked-open",
        ),
    )
    yield (
        inbox,
        "",
        _message(
            sender="Office <office@client.example>",
            to=me,
            subject="Automatische Antwort: Rückfrage zur Rechnung",
            body="Ich bin bis zum 30.11. nicht im Büro.",
            days_ago=8,
            message_id="autoreply-office",
            reply_to="sent-asked-open",
            headers={"Auto-Submitted": "auto-replied"},
        ),
    )
    yield (
        sent,
        seen,
        _message(
            sender=me,
            to="Friend <friend@friends.example>",
            subject="Danke",
            body="Danke dir, passt so.",
            days_ago=3,
            message_id="sent-no-request",
        ),
    )


# What each invented message is, per agent: the label and the fields, by
# the local part of its Message-ID. live/mailbox-agents/gold.py writes the gold files of
# the test account from it.
_NO_NEAR_MISS: dict[str, str | None] = {"near_miss": None}

GOLD: dict[str, dict[str, tuple[str, dict[str, str | None]]]] = {
    "inv-cloudhost-1": {
        "invoices": ("invoice", {"near_miss": None}),
        "inquiries": ("other", {}),
    },
    "inv-telco-1": {
        "invoices": ("invoice", {"near_miss": None}),
        "inquiries": ("other", {}),
    },
    "inv-paperworks-1": {
        "invoices": ("invoice", _NO_NEAR_MISS),
        "inquiries": ("other", {}),
    },
    "inv-receipt-1": {
        "invoices": ("invoice", _NO_NEAR_MISS),
        "inquiries": ("other", {}),
    },
    "near-reminder-1": {
        "invoices": ("other", {"near_miss": "reminder"}),
        "inquiries": ("other", {}),
    },
    "near-quote-1": {
        "invoices": ("other", {"near_miss": "quotation"}),
        "inquiries": ("other", {}),
    },
    "near-order-1": {
        "invoices": ("other", {"near_miss": "order_confirmation"}),
        "inquiries": ("other", {}),
    },
    "near-receipt-1": {
        "invoices": ("other", {"near_miss": "payment_receipt"}),
        "inquiries": ("other", {}),
    },
    "inquiry-1": {
        "invoices": ("other", _NO_NEAR_MISS),
        "inquiries": ("inquiry", {}),
    },
    "newsletter-1": {
        "invoices": ("other", _NO_NEAR_MISS),
        "inquiries": ("other", {}),
    },
    "reply-partner": {
        "invoices": ("other", _NO_NEAR_MISS),
        "inquiries": ("other", {}),
    },
    "autoreply-office": {
        "invoices": ("other", _NO_NEAR_MISS),
        "inquiries": ("other", {}),
    },
    "sent-asked-answered": {"awaiting_reply": ("expects_reply", {})},
    "sent-asked-open": {"awaiting_reply": ("expects_reply", {})},
    "sent-no-request": {"awaiting_reply": ("no_reply", {})},
}
