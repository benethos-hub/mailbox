"""What the model must answer about a sent message, and the text it is given."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from ...records import MailMessage
from .text import own_text

__all__ = ["MAX_SUBJECT", "MAX_TEXT", "Answer", "parts", "render"]

# The text written is cut here. A request stands near its end, which a long
# message keeps by being cut from the front.
MAX_TEXT = 4000

# The subject is cut here. A reply keeps the subject a stranger chose, so
# no mail can blow up a call. The same cut goes to the model and to the
# evidence check.
MAX_SUBJECT = 300


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expects_reply: bool
    quote: str


def render(message: MailMessage) -> str:
    """Recipients, subject and the text the sender wrote, without what it
    quotes."""
    to = _to(message) or "(none)"
    return f"To: {to}\nSubject: {_subject(message)}\n\n{_text(message)}"


def parts(message: MailMessage) -> list[str]:
    """The parts of the mail :func:`render` gives the model, without its
    frame: what a quote is looked up in."""
    return [_to(message), _subject(message), _text(message)]


def _to(message: MailMessage) -> str:
    """The recipients, to and cc, empty for none."""
    return ", ".join(a.email for a in (*message.to, *message.cc))


def _subject(message: MailMessage) -> str:
    return (message.subject or "")[:MAX_SUBJECT]


def _text(message: MailMessage) -> str:
    """The end of what the sender wrote, without what it quotes."""
    return own_text(message.text)[-MAX_TEXT:]
