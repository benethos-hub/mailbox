"""Schema 5, the baseline: every table of the state file as the old steps
left it at schema 4, and ``meta``, which step 5 of the old ones made.

A new database begins here, on a file as on a server. A file the old
steps brought to schema 5 is marked as here and runs nothing of it.

Frozen: written out here, not taken from the definitions in
``schema.py``, which a later revision changes.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op

from benethos_mailbox_agents.store.revisions import NUMBER, TEXT, Revision


def _text(name: str, *, required: bool = True) -> sa.Column[Any]:
    return sa.Column(name, TEXT, nullable=not required)


def _number(name: str, *, zero: bool = False) -> sa.Column[Any]:
    return sa.Column(
        name,
        NUMBER,
        nullable=False,
        server_default=sa.literal_column("0") if zero else None,
    )


def _id() -> sa.Column[Any]:
    return sa.Column("id", NUMBER, primary_key=True, nullable=True)


def _one() -> sa.Column[Any]:
    return sa.Column(
        "id",
        NUMBER,
        sa.CheckConstraint("id = 1"),
        primary_key=True,
        nullable=True,
        autoincrement=False,
    )


class R0005Baseline(Revision):
    version = 5

    def steps(self) -> None:
        op.create_table("cursor", _one(), _text("state"), _text("updated"))
        op.create_table("passes", _one(), _text("finished"))
        op.create_table(
            "messages",
            sa.Column("account_id", TEXT, primary_key=True, nullable=False),
            sa.Column("message_id", TEXT, primary_key=True, nullable=False),
            sa.Column(
                "state",
                TEXT,
                sa.CheckConstraint(
                    "state IN ('pending', 'skipped', 'decided', 'done', 'failed')"
                ),
                nullable=False,
            ),
            _number("attempts", zero=True),
            _text("next_attempt"),
            _text("created"),
            _text("updated"),
        )
        op.create_index("messages_by_state", "messages", ["state", "next_attempt"])
        op.create_table(
            "steps",
            _id(),
            _text("account_id"),
            _text("message_id"),
            _text("step"),
            _text("prompt_version"),
            _text("model_alias"),
            _text("model"),
            _text("result"),
            _number("tokens_in", zero=True),
            _number("tokens_out", zero=True),
            _number("duration_ms", zero=True),
            _text("at"),
        )
        op.create_index(
            "steps_by_message",
            "steps",
            ["account_id", "message_id", "step", "prompt_version", "model_alias"],
        )
        op.create_index("steps_by_time", "steps", ["step", "at"])
        op.create_table(
            "actions",
            _id(),
            _text("account_id"),
            _text("message_id"),
            _text("action"),
            _text("argument"),
            _text("before"),
            _text("stage"),
            _number("executed"),
            _text("at"),
        )
        op.create_index("actions_by_message", "actions", ["account_id", "message_id"])
        op.create_table(
            "open_items",
            sa.Column("account_id", TEXT, primary_key=True, nullable=False),
            sa.Column("message_id", TEXT, primary_key=True, nullable=False),
            _text("thread_id", required=False),
            _text("opened"),
            _text("due"),
            _number("keyword_set", zero=True),
            _text("closed", required=False),
            _text("reason", required=False),
            _text("keyword_recorded_stage", required=False),
        )
        op.create_index(
            "open_items_by_thread", "open_items", ["account_id", "thread_id"]
        )
        op.create_index("open_items_by_due", "open_items", ["closed", "due"])
        op.create_table(
            "calls",
            _id(),
            _text("account_id"),
            _text("message_id"),
            _text("request"),
            _text("answer"),
            _text("at"),
        )
        op.create_index("calls_by_time", "calls", ["at"])
        op.create_table(
            "profile",
            _one(),
            _text("agent"),
            _text("instance", required=False),
            _text("agent_version"),
            _text("package_version"),
            _text("stage"),
            _text("accounts"),
            _text("keyword"),
            _text("poll_seconds"),
            _text("gateway_timeout_seconds"),
            _text("model_alias"),
            _text("prompt_version"),
            _text("started"),
        )
        op.create_table(
            "meta",
            sa.Column("key", TEXT, primary_key=True, nullable=True),
            _text("value", required=False),
        )


revision, down_revision, upgrade = R0005Baseline.alembic()

__all__ = ["down_revision", "revision", "upgrade"]
