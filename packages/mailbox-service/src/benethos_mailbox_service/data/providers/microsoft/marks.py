"""Answered and forwarded on Exchange (UNIFORM 6.4).

Outlook keeps no keywords with ``$``. It keeps the verb last carried out
on a message instead (PidTagLastVerbExecuted, MS-OXOMSG 2.2.1.4): a reply
to the sender or to all, or a forward. Graph reads and writes it as an
extended property, beside the icon Outlook shows for it
(PidTagIconIndex) and when it happened (PidTagLastVerbExecutionTime).
One verb at a time: a message is answered or forwarded, never both, as
Outlook shows it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ....common.clock import utc_now
from ...models import Mark
from .shapes import Message as GraphMessage

VERB = "Integer 0x1081"
VERB_TIME = "SystemTime 0x1082"
ICON = "Integer 0x1080"
# Graph answers the verb along with the message when asked to expand it.
EXPAND = f"singleValueExtendedProperties($filter=id eq '{VERB}')"

# The verbs of a reply to the sender, to all, and of a forward.
_MARKS = {102: Mark.ANSWERED, 103: Mark.ANSWERED, 104: Mark.FORWARDED}
_VERBS = {Mark.ANSWERED: 102, Mark.FORWARDED: 104}
# Outlook's icons for a replied and a forwarded mail. Without a verb it
# chooses the icon itself.
_ICONS = {Mark.ANSWERED: 261, Mark.FORWARDED: 262}
_OWN_ICON = -1

WRITTEN = frozenset(_VERBS)


def read(item: GraphMessage) -> Mark | None:
    """The mark of the verb the message carries, if any."""
    for prop in item.single_value_extended_properties:
        if (prop.id or "").lower() == VERB.lower():
            try:
                return _MARKS.get(int(prop.value or ""))
            except ValueError:
                return None
    return None


def patch(mark: Mark | None, now: datetime | None = None) -> dict[str, Any]:
    """The part of a PATCH body that sets the verb of ``mark``, or none."""
    if mark is None:
        values = [(VERB, "0"), (ICON, str(_OWN_ICON))]
    else:
        when = (now or utc_now()).astimezone(UTC)
        values = [
            (VERB, str(_VERBS[mark])),
            (ICON, str(_ICONS[mark])),
            (VERB_TIME, when.strftime("%Y-%m-%dT%H:%M:%SZ")),
        ]
    return {
        "singleValueExtendedProperties": [
            {"id": prop, "value": value} for prop, value in values
        ]
    }
