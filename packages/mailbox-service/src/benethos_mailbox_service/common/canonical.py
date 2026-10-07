"""A value as JSON text, written one way for each purpose.

``compact`` is for what goes on: a body, a cursor. ``canonical`` is for
what is hashed or compared: the same value always gives the same text,
whatever order its keys were in. It escapes every character beyond
ASCII, so the text does not depend on how a value was spelled either.
A number stays as Python holds it: ``1`` and ``1.0`` differ. A value read
through a model of the API has one type per field, so it does not meet
that.
"""

from __future__ import annotations

import json


def compact(value: object) -> str:
    """``value`` as JSON without spaces, UTF-8 text as it is."""
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def canonical(value: object) -> str:
    """``value`` as JSON for a hash: keys sorted, no spaces, ASCII."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"))
