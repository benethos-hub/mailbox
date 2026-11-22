"""The gold format: mail a person labelled by hand.

One JSON object per line: the account id and the message id, the label
the agent should give, and for an extracting agent the value each field
should have, ``null`` for a field the message does not fill. The mail
itself is fetched by its id when the evaluation runs, so a gold file holds
ids and labels only. A line that starts with ``#`` and an empty line are
skipped. See docs/mailbox-agents/concept/evaluation.md.

    {"account_id": "acc1", "message_id": "m1", "label": "other",
     "fields": {"near_miss": "reminder"}}

A gold file that points at real mail lives under ``data/`` and is never
versioned.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from ..errors import ConfigError, describe_invalid
from ..records import MessageRef

__all__ = ["GoldItem", "load_gold"]


class GoldItem(BaseModel):
    """One labelled message."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    account_id: str = Field(min_length=1)
    message_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    fields: dict[str, str | None] = Field(default_factory=dict)
    note: str | None = None

    @property
    def ref(self) -> MessageRef:
        return MessageRef(account_id=self.account_id, message_id=self.message_id)


def load_gold(path: Path) -> list[GoldItem]:
    """The items of the gold file at ``path``. A line that is no JSON, does
    not fit the format, or names a message a second time is a
    :class:`ConfigError` naming the line."""
    if not path.is_file():
        raise ConfigError(f"no gold file {path.name}")
    items: list[GoldItem] = []
    seen: set[MessageRef] = set()
    # utf-8-sig: an editor may start the file with the mark of UTF-8.
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    for number, line in enumerate(lines, 1):
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        try:
            item = GoldItem.model_validate(json.loads(text))
        except ValueError as exc:
            raise ConfigError(
                f"{path.name} line {number}: {describe_invalid(exc)}"
            ) from None
        if item.ref in seen:
            raise ConfigError(f"{path.name} line {number}: the message is there twice")
        seen.add(item.ref)
        items.append(item)
    if not items:
        raise ConfigError(f"{path.name} holds no labelled message")
    return items
