"""The secrets the service holds in plain text, kept out of what it writes.

The second line of defence (CONCEPT 7.4): no code logs a secret or puts
one into an error text on purpose. Whatever still carries one, a
library's message or a traceback, is written with ``***`` in its place.
A secret is noted where it is decrypted or received. The newest
``KEPT`` are held: access tokens come anew every hour, and one in use
is noted again on its next decryption.

The one module of ``common`` with state of its own: a secret noted where
it is decrypted must be masked wherever a text is written, in every layer
and in the log, so the noted secrets are held process-wide.
"""

from __future__ import annotations

import threading
from collections import OrderedDict

MASK = "***"
# Shorter values are not masked: a password "a" would hide every "a".
SHORTEST = 6
KEPT = 256

_known: OrderedDict[str, None] = OrderedDict()
_lock = threading.Lock()


def note(secret: str) -> None:
    """Mask ``secret`` from now on, in every text ``redact`` sees."""
    if len(secret) < SHORTEST:
        return
    with _lock:
        _known[secret] = None
        _known.move_to_end(secret)
        while len(_known) > KEPT:
            _known.popitem(last=False)


def redact(text: str) -> str:
    """``text`` with every noted secret masked, the longest first, so one
    secret inside another leaves nothing of the longer behind."""
    with _lock:
        known = sorted(_known, key=len, reverse=True)
    for secret in known:
        if secret in text:
            text = text.replace(secret, MASK)
    return text
