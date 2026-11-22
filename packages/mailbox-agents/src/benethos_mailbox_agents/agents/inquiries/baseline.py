"""The question of inquiries answered by rules alone.

A message is an inquiry when its sender's domain is known, or when it
carries two phrases of an inquiry, or one phrase together with a date or a
rate. See docs/mailbox-agents/concept/agent-inquiries.md.
"""

from __future__ import annotations

from ...records import Decision, MailMessage
from .patterns import DATE, RATE, Patterns

__all__ = ["baseline"]


def baseline(message: MailMessage, patterns: Patterns) -> Decision:
    text = f"{message.subject or ''}\n{message.text[:4000]}"
    phrases = patterns.phrases_in(text)
    numbers = bool(DATE.search(text)) or bool(RATE.search(text))
    inquiry = (
        patterns.sender_known(message.sender)
        or len(phrases) >= 2
        or (len(phrases) == 1 and numbers)
    )
    return Decision(label="inquiry" if inquiry else "other", source="baseline")
