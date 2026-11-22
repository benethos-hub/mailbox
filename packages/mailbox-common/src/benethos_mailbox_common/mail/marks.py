"""The marks of RFC 8621 a person sees on a message, and the words for
them. The UI and the MCP server show marks through these and spell no
``$`` keyword of their own (docs/mailbox-service/UNIFORM.md, U3). How the UI draws one
is the UI's.

``$seen`` and ``$flagged`` are no marks here: they are read and starred.
A ``$`` keyword that is no mark, such as ``$important``, is a keyword.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Mark:
    """One mark: its keyword, the word a person reads, and whether a
    person cares to see it. ``$notjunk`` only says a mail is not junk,
    which shows nothing."""

    keyword: str
    word: str
    shown: bool = True


ANSWERED = Mark("$answered", "answered")
FORWARDED = Mark("$forwarded", "forwarded")
DRAFT = Mark("$draft", "draft")
JUNK = Mark("$junk", "junk")
NOT_JUNK = Mark("$notjunk", "not junk", shown=False)
PHISHING = Mark("$phishing", "phishing")

MARKS: tuple[Mark, ...] = (ANSWERED, FORWARDED, DRAFT, JUNK, NOT_JUNK, PHISHING)
_BY_KEYWORD = {mark.keyword: mark for mark in MARKS}


def mark_of(keyword: str) -> Mark | None:
    """The mark a keyword is, compared without case, or None."""
    return _BY_KEYWORD.get(keyword.lower())


def marks_of(keywords: Iterable[str]) -> list[Mark]:
    """The marks among a message's keywords that a person sees, in the
    order of ``MARKS``."""
    held = {keyword.lower() for keyword in keywords}
    return [mark for mark in MARKS if mark.shown and mark.keyword in held]


def protocol(keyword: str) -> bool:
    """Whether a keyword belongs to the mail protocol rather than to a
    person: a mark, or another keyword starting with ``$``."""
    return keyword.startswith("$")


def personal(keywords: Iterable[str]) -> list[str]:
    """The keywords a person sets, without those of the mail protocol."""
    return [keyword for keyword in keywords if not protocol(keyword)]
