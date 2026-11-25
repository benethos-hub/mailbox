"""What the baseline of inquiries knows: sender domains and phrases.

The phrases built in are those a project inquiry usually carries. A file
named in MAILBOX_AGENTS_INQUIRIES_PATTERNS_FILE adds the sender domains and
phrases the owner's own gold set shows, such as the domains of the agencies
that write. It is JSON, like the list of categorization:

    {"domains": ["staffing.example"], "phrases": ["für einen kunden"]}

See docs/mailbox-agents/concept/agent-inquiries.md.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

from pydantic import BaseModel, ConfigDict, field_validator

from ...errors import ConfigError, describe_invalid
from ...records import Address

__all__ = ["DATE", "PHRASES", "RATE", "Patterns", "load_patterns"]

PHRASES = (
    "projektanfrage",
    "projekt anfrage",
    "für einen kunden",
    "für unseren kunden",
    "suchen wir",
    "wir suchen",
    "freelancer",
    "freiberufler",
    "einsatzort",
    "stundensatz",
    "auslastung",
    "project inquiry",
    "project request",
    "on behalf of our client",
    "we are looking for",
    "contract role",
    "day rate",
    "hourly rate",
)

# A start date, such as 01.02.2027, 1.2.27 or 2027-02-01.
DATE = re.compile(r"\b(?:\d{1,2}\.\d{1,2}\.(?:\d{4}|\d{2})|\d{4}-\d{2}-\d{2})\b")

# A rate, such as 95 EUR, 95 €/h, 95,- € or EUR 95.
RATE = re.compile(
    r"(?:\b\d{2,4}(?:[.,]\d{1,2}|,-)?\s?(?:eur|€)(?:\s?/\s?(?:h|std|stunde|tag|day))?)"
    r"|(?:\b(?:eur|€)\s?\d{2,4}\b)",
    flags=re.IGNORECASE,
)


class Patterns(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    domains: tuple[str, ...] = ()
    phrases: tuple[str, ...] = ()

    @field_validator("domains", "phrases")
    @classmethod
    def _lower(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        found = tuple(_folded(v).strip().lstrip("@") for v in value)
        if any(not v for v in found):
            raise ValueError("an empty entry")
        return found

    def sender_known(self, address: Address | None) -> bool:
        if address is None:
            return False
        domain = address.domain
        return any(domain == d or domain.endswith("." + d) for d in self.domains)

    def phrases_in(self, text: str) -> list[str]:
        lowered = _folded(text)
        return [p for p in (*PHRASES, *self.phrases) if p in lowered]


def _folded(text: str) -> str:
    """``text`` in Unicode NFC and lower case, as phrases are compared."""
    return unicodedata.normalize("NFC", text).lower()


def load_patterns(path: Path | None) -> Patterns:
    """The patterns of ``path``, or those built in when it is None."""
    if path is None:
        return Patterns()
    try:
        # utf-8-sig: an editor may start the file with the mark of UTF-8.
        text = path.read_text(encoding="utf-8-sig")
        return Patterns.model_validate(json.loads(text))
    except OSError as exc:
        raise ConfigError(
            f"the patterns {path.name} cannot be read ({type(exc).__name__})"
        ) from None
    except ValueError as exc:
        raise ConfigError(
            f"the patterns {path.name}: {describe_invalid(exc)}"
        ) from None
