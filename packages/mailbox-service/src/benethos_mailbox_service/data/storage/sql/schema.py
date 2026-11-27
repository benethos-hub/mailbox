"""The tables of schema 26 as SQLAlchemy describes them: the one
description of the schema the repositories and the export read.

Written by hand after the schema the migrations make (``sqlite/
migrations/``), column for column and index for index, and held to it
by a test. Read back from a database, the description would lose
``ON DELETE CASCADE`` and ``AUTOINCREMENT``.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa

from benethos_mailbox_common.storage import dialect

METADATA = sa.MetaData()


def _key(name: str) -> sa.Column[Any]:
    """A key of text. SQLite keeps it without NOT NULL, as the migrations
    made it."""
    return sa.Column(name, dialect.TEXT, primary_key=True, nullable=True)


def _part(name: str) -> sa.Column[Any]:
    """A column of a key of several."""
    return sa.Column(name, dialect.TEXT, primary_key=True, nullable=False)


def _str(
    name: str, *, required: bool = False, default: str | None = None
) -> sa.Column[Any]:
    return sa.Column(name, dialect.TEXT, nullable=not required, server_default=default)


def _int(name: str, *, required: bool = False, zero: bool = False) -> sa.Column[Any]:
    return sa.Column(
        name,
        dialect.NUMBER,
        nullable=not required,
        server_default=sa.literal_column("0") if zero else None,
    )


def _bytes(name: str) -> sa.Column[Any]:
    return sa.Column(name, dialect.BYTES, nullable=False)


def _ref(name: str, target: str, *, cascade: bool = True) -> sa.Column[Any]:
    """A column of text that must refer to ``target``, and goes with it
    when ``cascade``."""
    return sa.Column(
        name,
        dialect.TEXT,
        sa.ForeignKey(target, ondelete="CASCADE" if cascade else None),
        nullable=False,
    )


meta = sa.Table(
    "meta",
    METADATA,
    _key("key"),
    _str("value"),
)

accounts = sa.Table(
    "accounts",
    METADATA,
    _key("id"),
    _str("provider", required=True),
    _str("email", required=True),
    _str("display_name"),
    _str("status", required=True),
    _str("settings", required=True, default="{}"),
    _str("abilities"),
    _int("position"),
    sa.Index("accounts_position", "position", unique=True),
)

users = sa.Table(
    "users",
    METADATA,
    _key("id"),
    _str("name", required=True),
    _str("roles", required=True, default="[]"),
    _str("grants", required=True, default="[]"),
    _int("disabled", required=True, zero=True),
    _int("ui_sign_in", required=True, zero=True),
    _str("service", required=True, default="[]"),
    _int("position"),
    _str("name_lower"),
    sa.Index("users_name_lower", "name_lower", unique=True),
    sa.Index("users_position", "position", unique=True),
)

roles = sa.Table(
    "roles",
    METADATA,
    _key("id"),
    _str("grants", required=True, default="[]"),
    _str("service", required=True, default="[]"),
    _int("position"),
    sa.Index("roles_position", "position", unique=True),
)

keys = sa.Table(
    "keys",
    METADATA,
    _key("key_id"),
    _bytes("nonce"),
    _bytes("ciphertext"),
    # The one default that is not a fixed value. The insert sets the
    # time itself.
    sa.Column(
        "created_at",
        dialect.TEXT,
        nullable=False,
        server_default=sa.func.current_timestamp(),
    ),
)

activity = sa.Table(
    "activity",
    METADATA,
    _key("id"),
    _str("at", required=True),
    _str("activity", required=True),
    _str("user_id"),
    _str("user_name", required=True),
    _str("credential"),
    _str("record"),
    _str("source"),
    _str("outcome", required=True),
    _str("detail", required=True),
    sa.Index("activity_record", "record", "at"),
    sa.Index("activity_user", "user_id", "at"),
    sa.Index("activity_at", "at"),
)

sends = sa.Table(
    "sends",
    METADATA,
    _key("id"),
    _str("created_at", required=True),
    _str("user_id", required=True),
    _str("credential_id"),
    _str("account_id", required=True),
    _str("operation", required=True),
    _str("recipients", required=True),
    _str("outcome", required=True),
    _str("error"),
    _str("refused", required=True),
    _str("message_id_header"),
    _str("outbox_job_id"),
    _str("recipients_folded", required=True, default=""),
    sa.Index("sends_user", "user_id", "account_id", "created_at"),
    sa.Index("sends_account", "account_id", "created_at"),
)

changes = sa.Table(
    "changes",
    METADATA,
    dialect.counter("seq"),
    _ref("account_id", "accounts.id"),
    _str("message_id", required=True),
    _str("type", required=True),
    _str("at", required=True),
    _str("folder_id"),
    sa.Index("changes_at", "at"),
    sa.Index("changes_account", "account_id", "seq"),
    **dialect.COUNTED,
)

credentials = sa.Table(
    "credentials",
    METADATA,
    sa.Column(
        "account_id",
        dialect.TEXT,
        sa.ForeignKey("accounts.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    ),
    _part("field"),
    _ref("key_id", "keys.key_id", cascade=False),
    _bytes("nonce"),
    _bytes("ciphertext"),
    _str("updated_at", required=True),
)

folder_states = sa.Table(
    "folder_states",
    METADATA,
    sa.Column(
        "account_id",
        dialect.TEXT,
        sa.ForeignKey("accounts.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    ),
    _part("folder_id"),
    _str("state", required=True),
)

idempotency = sa.Table(
    "idempotency",
    METADATA,
    sa.Column(
        "account_id",
        dialect.TEXT,
        sa.ForeignKey("accounts.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    ),
    _part("user_id"),
    _part("key"),
    _str("operation", required=True),
    _str("request_hash", required=True),
    _str("result", required=True),
    _str("created_at", required=True),
    sa.Index("idempotency_created", "created_at"),
)

message_index = sa.Table(
    "message_index",
    METADATA,
    dialect.counter("seq"),
    _ref("account_id", "accounts.id"),
    _str("id", required=True),
    _str("native_id", required=True),
    _str("folder_id", required=True),
    _str("header"),
    _str("thread_id"),
    sa.UniqueConstraint("account_id", "id"),
    sa.UniqueConstraint("account_id", "native_id"),
    sa.Index("message_index_header", "account_id", "header"),
    sa.Index("message_index_thread", "account_id", "thread_id"),
    sa.Index("message_index_folder", "account_id", "folder_id"),
    **dialect.COUNTED,
)

outbox = sa.Table(
    "outbox",
    METADATA,
    _key("id"),
    _ref("account_id", "accounts.id"),
    _str("user_id", required=True),
    _str("credential_id"),
    _str("operation", required=True),
    _str("draft_id", required=True),
    _str("digest", required=True),
    _str("message_id_header", required=True),
    _str("recipients", required=True),
    _str("state", required=True),
    _int("attempts", required=True),
    _str("due_at", required=True),
    _str("expires_at", required=True),
    _str("send_at"),
    _str("last_error"),
    _str("unclear_since"),
    _str("created_at", required=True),
    _str("finished_at"),
    sa.Index("outbox_state", "state", "due_at"),
    sa.Index("outbox_account", "account_id", "created_at"),
)

passkeys = sa.Table(
    "passkeys",
    METADATA,
    _key("id"),
    _ref("user_id", "users.id"),
    _str("name", required=True),
    sa.Column("credential_id", dialect.BYTES, nullable=False, unique=True),
    _bytes("credential"),
    _int("sign_count", required=True, zero=True),
    _str("created_at", required=True),
    _str("last_used_at"),
    sa.Index("passkeys_user", "user_id"),
)

passwords = sa.Table(
    "passwords",
    METADATA,
    sa.Column(
        "user_id",
        dialect.TEXT,
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=True,
    ),
    _str("hash", required=True),
    _int("must_change", required=True, zero=True),
    _str("updated_at", required=True),
    _str("last_sign_in_at"),
)

recovery_codes = sa.Table(
    "recovery_codes",
    METADATA,
    sa.Column(
        "user_id",
        dialect.TEXT,
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    ),
    _str("key_id", required=True),
    _part("hash"),
    _str("used_at"),
)

thread_links = sa.Table(
    "thread_links",
    METADATA,
    dialect.counter("seq"),
    _ref("account_id", "accounts.id"),
    _str("header", required=True),
    _str("thread_id", required=True),
    sa.UniqueConstraint("account_id", "header"),
    sa.Index("thread_links_thread", "account_id", "thread_id"),
    **dialect.COUNTED,
)

tokens = sa.Table(
    "tokens",
    METADATA,
    _key("id"),
    _ref("user_id", "users.id"),
    _str("name", required=True),
    sa.Column("token_hash", dialect.TEXT, nullable=False, unique=True),
    _str("created_at", required=True),
    _str("expires_at"),
    _str("last_used_at"),
    _str("revoked_at"),
)

totp_devices = sa.Table(
    "totp_devices",
    METADATA,
    _key("id"),
    _ref("user_id", "users.id"),
    _str("name", required=True),
    _str("key_id", required=True),
    _bytes("nonce"),
    _bytes("ciphertext"),
    _str("created_at", required=True),
    _int("last_step"),
    _str("last_used_at"),
    sa.Index("totp_devices_user", "user_id"),
)

webhooks = sa.Table(
    "webhooks",
    METADATA,
    _key("id"),
    _str("user_id", required=True),
    _str("url", required=True),
    _str("events", required=True),
    _str("accounts"),
    _str("created_at", required=True),
    _ref("key_id", "keys.key_id", cascade=False),
    _bytes("nonce"),
    _bytes("ciphertext"),
    _int("cursor", required=True),
    _int("attempts", required=True, zero=True),
    _str("next_attempt_at"),
    _str("last_delivery_at"),
    _str("last_error"),
)

attachment_links = sa.Table(
    "attachment_links",
    METADATA,
    _key("id"),
    sa.Column("secret_hash", dialect.TEXT, nullable=False, unique=True),
    _ref("account_id", "accounts.id"),
    _str("message_id", required=True),
    _str("attachment_id", required=True),
    _ref("token_id", "tokens.id"),
    _str("expires_at", required=True),
    _str("redeemed_at"),
    _str("redeemed_by"),
    sa.Index("attachment_links_expires", "expires_at"),
)

webhook_attempts = sa.Table(
    "webhook_attempts",
    METADATA,
    dialect.counter("seq"),
    _ref("webhook_id", "webhooks.id"),
    _str("delivery_id", required=True),
    _str("at", required=True),
    _int("events", required=True),
    _int("status"),
    _str("error"),
    sa.Index("webhook_attempts_webhook", "webhook_id", "seq"),
    **dialect.COUNTED,
)
