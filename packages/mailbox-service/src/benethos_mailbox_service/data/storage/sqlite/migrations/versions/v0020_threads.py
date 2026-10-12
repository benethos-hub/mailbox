"""Schema 20: threads for accounts whose ids go through the index (IMAP).

Each entry of the index gets the thread it belongs to. ``thread_links``
ties every ``Message-ID`` a message names, its own and those it answers
or references, to that thread. A message that arrives later finds its
thread through any of them, also when the message it answers came after
it or is gone. A thread is found by its messages through the index on
``(account_id, thread_id)``.

The entries already there have no thread yet. The sync reads their
headers and threads them in portions.
"""

from __future__ import annotations

from ..migration import Migration


class V0020Threads(Migration):
    version = 20
    statements = (
        "ALTER TABLE message_index ADD COLUMN thread_id TEXT",
        "CREATE INDEX message_index_thread ON message_index (account_id, thread_id)",
        """
        CREATE TABLE thread_links (
            account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
            header TEXT NOT NULL,
            thread_id TEXT NOT NULL,
            PRIMARY KEY (account_id, header)
        )
        """,
        "CREATE INDEX thread_links_thread ON thread_links (account_id, thread_id)",
    )
