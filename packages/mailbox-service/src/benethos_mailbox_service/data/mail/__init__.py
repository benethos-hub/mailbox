"""Messages in their own format (RFC 5322), whichever protocol carries them.

``compose`` builds an outgoing message, ``parse`` reads one, ``convert``
turns a parsed message into the neutral model. IMAP, POP3 and any adapter
that sees raw messages share them. The domain uses ``compose`` for replies.
``fields`` reads and writes one header field, and ``ThreadHeaders``
holds those that tie a message to its conversation. The text of an HTML-only
mail comes from ``benethos_mailbox_common.mail.plaintext``. Callers
import the modules from here, ``from ..mail import compose``, and call
``compose.build(...)``.
"""

from __future__ import annotations

from . import compose, convert, fields, parse
from .fields import ThreadHeaders

__all__ = ["ThreadHeaders", "compose", "convert", "fields", "parse"]
