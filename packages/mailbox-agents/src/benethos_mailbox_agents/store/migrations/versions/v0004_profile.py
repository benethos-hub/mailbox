"""The profile of the agent that writes the file, one row.

A process that reads the state file from outside, such as the cockpit,
does not hold the settings of the worker: not its stage, its accounts,
its poll seconds or its prompt version. The worker writes them here when
it starts, so a reader can tell what the file belongs to and judge its
health with the numbers of the worker. The two numbers of seconds are
decimal text, as the shared layer knows text, integers and bytes alone.
``accounts`` is a JSON list, empty for every account of the service
user. No secret, no text of a list and no address is kept.
"""

from __future__ import annotations

from ..migration import Migration

__all__ = ["V0004Profile"]


class V0004Profile(Migration):
    version = 4
    statements = (
        """
            CREATE TABLE profile (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                agent TEXT NOT NULL,
                instance TEXT,
                agent_version TEXT NOT NULL,
                package_version TEXT NOT NULL,
                stage TEXT NOT NULL,
                accounts TEXT NOT NULL,
                keyword TEXT NOT NULL,
                poll_seconds TEXT NOT NULL,
                gateway_timeout_seconds TEXT NOT NULL,
                model_alias TEXT NOT NULL,
                prompt_version TEXT NOT NULL,
                started TEXT NOT NULL
            )
        """,
    )
