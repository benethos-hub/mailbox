"""The state file of one agent, docs/concept/state.md.

The cursor of the change feed, the time of the loop's last progress, every
message the agent took up with its state, the steps of each and their
results, the actions taken or recorded with what was there before, the
open items of an agent with deadlines, and the calls to the model kept
for PROMPT_RETENTION_DAYS. Times are ISO 8601 text in UTC. A message is
named by its account id and its message id together.
"""

from __future__ import annotations

from ..migration import Migration

__all__ = ["V0001StateFile"]


class V0001StateFile(Migration):
    version = 1
    statements = (
        """
            CREATE TABLE cursor (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                state TEXT NOT NULL,
                updated TEXT NOT NULL
            )
        """,
        """
            CREATE TABLE passes (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                finished TEXT NOT NULL
            )
        """,
        """
            CREATE TABLE messages (
                account_id TEXT NOT NULL,
                message_id TEXT NOT NULL,
                state TEXT NOT NULL CHECK (
                    state IN ('pending', 'skipped', 'decided', 'done', 'failed')
                ),
                attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt TEXT NOT NULL,
                created TEXT NOT NULL,
                updated TEXT NOT NULL,
                PRIMARY KEY (account_id, message_id)
            )
        """,
        """
            CREATE INDEX messages_by_state ON messages (state, next_attempt)
        """,
        """
            CREATE TABLE steps (
                id INTEGER PRIMARY KEY,
                account_id TEXT NOT NULL,
                message_id TEXT NOT NULL,
                step TEXT NOT NULL,
                prompt_version TEXT NOT NULL,
                model_alias TEXT NOT NULL,
                model TEXT NOT NULL,
                result TEXT NOT NULL,
                tokens_in INTEGER NOT NULL DEFAULT 0,
                tokens_out INTEGER NOT NULL DEFAULT 0,
                duration_ms INTEGER NOT NULL DEFAULT 0,
                at TEXT NOT NULL
            )
        """,
        """
            CREATE INDEX steps_by_message ON steps (
                account_id, message_id, step, prompt_version, model_alias
            )
        """,
        """
            CREATE INDEX steps_by_time ON steps (step, at)
        """,
        """
            CREATE TABLE actions (
                id INTEGER PRIMARY KEY,
                account_id TEXT NOT NULL,
                message_id TEXT NOT NULL,
                action TEXT NOT NULL,
                argument TEXT NOT NULL,
                before TEXT NOT NULL,
                stage TEXT NOT NULL,
                executed INTEGER NOT NULL,
                at TEXT NOT NULL
            )
        """,
        """
            CREATE INDEX actions_by_message ON actions (account_id, message_id)
        """,
        """
            CREATE TABLE open_items (
                account_id TEXT NOT NULL,
                message_id TEXT NOT NULL,
                thread_id TEXT,
                opened TEXT NOT NULL,
                due TEXT NOT NULL,
                keyword_set INTEGER NOT NULL DEFAULT 0,
                closed TEXT,
                reason TEXT,
                PRIMARY KEY (account_id, message_id)
            )
        """,
        """
            CREATE INDEX open_items_by_thread ON open_items (account_id, thread_id)
        """,
        """
            CREATE INDEX open_items_by_due ON open_items (closed, due)
        """,
        """
            CREATE TABLE calls (
                id INTEGER PRIMARY KEY,
                account_id TEXT NOT NULL,
                message_id TEXT NOT NULL,
                request TEXT NOT NULL,
                answer TEXT NOT NULL,
                at TEXT NOT NULL
            )
        """,
        """
            CREATE INDEX calls_by_time ON calls (at)
        """,
    )
