"""The tables of the state file as SQLAlchemy defines them: the shape the
store reads and writes through, on a file of SQLite or a schema on a
server. Written by hand to match what the steps of the file made up to
schema 4 and what step 5 added, ``meta``, and held to both by a test.

Times are ISO text in UTC, a truth 0 or 1, JSON text: the three kinds
of the storage, text, numbers and bytes, as an export knows them.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa

from benethos_mailbox_common.storage import dialect

METADATA = sa.MetaData()

# The states a message can be in.
STATE_CHECK = "state IN ('pending', 'skipped', 'decided', 'done', 'failed')"


def _text(name: str, *, required: bool = True) -> sa.Column[Any]:
    return sa.Column(name, dialect.TEXT, nullable=not required)


def _number(name: str, *, zero: bool = False) -> sa.Column[Any]:
    return sa.Column(
        name,
        dialect.NUMBER,
        nullable=False,
        server_default=sa.literal_column("0") if zero else None,
    )


def _id() -> sa.Column[Any]:
    """A key that counts up, as SQLite keeps an INTEGER PRIMARY KEY: without
    NOT NULL, as the steps of the file made it."""
    return sa.Column("id", dialect.NUMBER, primary_key=True, nullable=True)


def _one() -> sa.Column[Any]:
    """The key of a table of one row."""
    return sa.Column(
        "id",
        dialect.NUMBER,
        sa.CheckConstraint("id = 1"),
        primary_key=True,
        nullable=True,
        autoincrement=False,
    )


cursor = sa.Table("cursor", METADATA, _one(), _text("state"), _text("updated"))

passes = sa.Table("passes", METADATA, _one(), _text("finished"))

messages = sa.Table(
    "messages",
    METADATA,
    sa.Column("account_id", dialect.TEXT, primary_key=True, nullable=False),
    sa.Column("message_id", dialect.TEXT, primary_key=True, nullable=False),
    sa.Column("state", dialect.TEXT, sa.CheckConstraint(STATE_CHECK), nullable=False),
    _number("attempts", zero=True),
    _text("next_attempt"),
    _text("created"),
    _text("updated"),
    sa.Index("messages_by_state", "state", "next_attempt"),
)

steps = sa.Table(
    "steps",
    METADATA,
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
    sa.Index(
        "steps_by_message",
        "account_id",
        "message_id",
        "step",
        "prompt_version",
        "model_alias",
    ),
    sa.Index("steps_by_time", "step", "at"),
)

actions = sa.Table(
    "actions",
    METADATA,
    _id(),
    _text("account_id"),
    _text("message_id"),
    _text("action"),
    _text("argument"),
    _text("before"),
    _text("stage"),
    _number("executed"),
    _text("at"),
    sa.Index("actions_by_message", "account_id", "message_id"),
)

open_items = sa.Table(
    "open_items",
    METADATA,
    sa.Column("account_id", dialect.TEXT, primary_key=True, nullable=False),
    sa.Column("message_id", dialect.TEXT, primary_key=True, nullable=False),
    _text("thread_id", required=False),
    _text("opened"),
    _text("due"),
    _number("keyword_set", zero=True),
    _text("closed", required=False),
    _text("reason", required=False),
    _text("keyword_recorded_stage", required=False),
    sa.Index("open_items_by_thread", "account_id", "thread_id"),
    sa.Index("open_items_by_due", "closed", "due"),
)

calls = sa.Table(
    "calls",
    METADATA,
    _id(),
    _text("account_id"),
    _text("message_id"),
    _text("request"),
    _text("answer"),
    _text("at"),
    sa.Index("calls_by_time", "at"),
)

profile = sa.Table(
    "profile",
    METADATA,
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

# The schema of the file, and what keeps account of it.
meta = sa.Table(
    "meta",
    METADATA,
    sa.Column("key", dialect.TEXT, primary_key=True, nullable=True),
    _text("value", required=False),
)
