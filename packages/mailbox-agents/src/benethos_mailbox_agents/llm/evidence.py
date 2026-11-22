"""The evidence check: whether a quote is in the text the model was given.

A label and every extracted field carry a quote. The code looks for the
quote in the parts of the mail the model was given, each part on its own:
sender, subject, attachment names, text. The frame the code writes around
them, such as ``Subject:``, is no part, and a quote that starts with one is
looked up without it. Both sides are brought to Unicode NFC and compared
word for word: case, punctuation, typographic quotes and dashes, and the
whitespace between words do not count, the words and their order do. A
changed or missing word is not forgiven, nor a first or last word cut
short. A quote of fewer than eight
letters and digits counts as not found, so ``e`` or a colon backs nothing.
A field whose quote is not found is dropped. A label whose quote is not
found makes the decision ``refused``: it is recorded and not acted on. See
docs/mailbox-agents/concept/safety.md.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence

from ..records import LABEL, Decision

__all__ = ["MIN_QUOTE", "check", "contains", "words"]

# The fewest letters and digits a quote must have to be found.
MIN_QUOTE = 8

# Everything between two words: whitespace, punctuation, quotes, dashes.
_BETWEEN = re.compile(r"[\W_]+", flags=re.UNICODE)
# The words of the frame render() writes before a part of the mail.
_FRAME = re.compile(r"^\s*(?:from|to|subject|attachments)\s*:", flags=re.IGNORECASE)


def words(text: str) -> str:
    """The words of ``text`` in Unicode NFC, in lower case, one space
    between each: what a quote is compared by."""
    folded = unicodedata.normalize("NFC", text).casefold()
    return _BETWEEN.sub(" ", folded).strip()


def contains(content: str, quote: str) -> bool:
    """Whether ``quote`` is in ``content``, word for word. A quote of fewer
    than :data:`MIN_QUOTE` letters and digits is in nothing."""
    needle = words(_FRAME.sub("", quote, count=1))
    if len(needle.replace(" ", "")) < MIN_QUOTE:
        return False
    # Whole words at both ends: a first or last word cut short is a
    # changed word.
    return f" {needle} " in f" {words(content)} "


def check(decision: Decision, parts: Sequence[str]) -> Decision:
    """``decision`` with every quote looked up in ``parts``, the parts of
    the mail the model was given, each on its own.

    Each evidence is marked ``found``. One that code already found by a
    rule stays found. A field whose quote is missing or
    not found is dropped. A decision whose label has no quote that is
    found is ``refused`` with the reason ``evidence``.
    """
    evidence = tuple(
        item.model_copy(
            update={
                "found": item.found is True
                or any(contains(part, item.quote) for part in parts)
            }
        )
        for item in decision.evidence
    )
    backed = {item.field for item in evidence if item.found}
    fields = {name: value for name, value in decision.fields.items() if name in backed}
    refused = decision.refused
    if refused is None and LABEL not in backed:
        refused = "evidence"
    return decision.model_copy(
        update={"evidence": evidence, "fields": fields, "refused": refused}
    )
