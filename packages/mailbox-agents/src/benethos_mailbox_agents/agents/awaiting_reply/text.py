"""What the rules of awaiting_reply read in a mail: the text its sender
wrote, without what it quotes, whether it asks for something, and whether
a message is an automatic answer.

The mailbox service exposes no header of a message (measured 2026-11-17),
so ``Auto-Submitted`` cannot be read. An automatic answer is told by its
sender and its subject (decided 2026-11-17), and what that misses is
counted by the evaluation. See docs/mailbox-agents/concept/agent-awaiting-reply.md.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta

from ...records import MailMessage

__all__ = [
    "add_working_days",
    "address",
    "asks",
    "automatic",
    "own_text",
    "written_paragraphs",
]

# Where the quoted part of a reply begins.
_QUOTE_START = re.compile(
    r"^(?:>|-{2,}\s*(?:original|ursprüngliche)|"
    r"on .+ wrote:|am .+ schrieb .+:|von:\s|from:\s)",
    flags=re.IGNORECASE,
)

# How much of a line the start of a quote is looked for in. The pattern
# with two ``.+`` takes time in the square of the line's length, and a
# line that opens a quote is short.
_QUOTE_LINE = 1000

REQUEST_PHRASES = (
    "bitte",
    "please",
    "können sie",
    "könnten sie",
    "kannst du",
    "könntest du",
    "could you",
    "can you",
    "would you",
    "let me know",
    "teilen sie mir mit",
    "geben sie mir bescheid",
    "gib mir bescheid",
    "melden sie sich",
    "rückmeldung",
    "i look forward to hearing",
    "ich freue mich auf ihre antwort",
)

AUTOMATIC_SENDERS = (
    "noreply",
    "no-reply",
    "donotreply",
    "do-not-reply",
    "mailer-daemon",
    "postmaster",
    "bounce",
)

AUTOMATIC_SUBJECTS = (
    "automatische antwort",
    "automatic reply",
    "autoreply",
    "auto-reply",
    "auto:",
    "abwesenheitsnotiz",
    "abwesend",
    "out of office",
    "out-of-office",
    "unzustellbar",
    "undeliverable",
    "delivery status notification",
    "mail delivery failed",
)


def _nfc(text: str) -> str:
    """``text`` in Unicode NFC, as the phrases here are written."""
    return unicodedata.normalize("NFC", text)


def own_text(text: str) -> str:
    """The text its sender wrote: everything before the quoted part. A
    line is looked at for the start of a quote in its first
    :data:`_QUOTE_LINE` characters, so a long line costs no more time than
    a short one."""
    lines = []
    for line in text.splitlines():
        if _QUOTE_START.match(_nfc(line).strip()[:_QUOTE_LINE]):
            break
        lines.append(line)
    return "\n".join(lines).strip()


def written_paragraphs(text: str) -> list[str]:
    """The paragraphs of the own text, a greeting of a few words left out."""
    paragraphs = [" ".join(p.split()) for p in re.split(r"\n\s*\n", own_text(text))]
    return [p for p in paragraphs if len(p.split()) >= 4]


def asks(text: str) -> bool:
    """Whether the last paragraph written holds a question mark or a
    request phrase: the rule of the baseline."""
    paragraphs = written_paragraphs(text)
    if not paragraphs:
        return False
    last = _nfc(paragraphs[-1]).lower()
    return "?" in last or any(phrase in last for phrase in REQUEST_PHRASES)


def address(message: MailMessage) -> str:
    """The sender's address in lower case, empty for a message without one."""
    return message.sender.email.lower() if message.sender else ""


def automatic(message: MailMessage) -> bool:
    """Whether a message looks like an automatic answer, by sender and
    subject."""
    local = address(message).partition("@")[0]
    subject = (message.subject or "").strip().lower()
    return any(name in local for name in AUTOMATIC_SENDERS) or subject.startswith(
        AUTOMATIC_SUBJECTS
    )


def add_working_days(start: datetime, days: int) -> datetime:
    """``days`` working days after ``start``, Monday to Friday, at the same
    time of day. A start on a weekend counts from the Monday after."""
    found = start
    while found.weekday() >= 5:
        found += timedelta(days=1)
    left = days
    while left > 0:
        found += timedelta(days=1)
        if found.weekday() < 5:
            left -= 1
    return found
