"""Schema 24: the index of messages is found by ``Message-ID``.

A list that meets a message in a place the index does not know asks
whether it knows the ``Message-ID`` elsewhere: then another program may
have moved the message, and the account is synced before the list gives
it an id. The question is asked with every such list, so it gets an
index on ``(account_id, header)``.
"""

from __future__ import annotations

from ..migration import Migration


class V0024IndexByHeader(Migration):
    version = 24
    statements = (
        "CREATE INDEX message_index_header ON message_index (account_id, header)",
    )
