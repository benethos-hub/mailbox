"""Mail going out: who it goes to, and what a send answered."""

from __future__ import annotations

from dataclasses import dataclass

# An address with an optional display name.
Recipient = tuple[str, str | None]


@dataclass(frozen=True, slots=True)
class Sent:
    message_id_header: str | None
    refused: list[str]
