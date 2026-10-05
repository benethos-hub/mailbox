"""Schema 1: accounts, users, roles, tokens."""

from __future__ import annotations

from .migration import Migration


class V0001AccountsUsers(Migration):
    version = 1
    statements = (
        """
        CREATE TABLE accounts (
            id TEXT PRIMARY KEY,
            provider TEXT NOT NULL,
            email TEXT NOT NULL,
            display_name TEXT,
            status TEXT NOT NULL,
            settings TEXT NOT NULL DEFAULT '{}'
        )
        """,
        """
        CREATE TABLE users (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            roles TEXT NOT NULL DEFAULT '[]',
            grants TEXT NOT NULL DEFAULT '[]',
            disabled INTEGER NOT NULL DEFAULT 0
        )
        """,
        """
        CREATE TABLE roles (
            id TEXT PRIMARY KEY,
            grants TEXT NOT NULL DEFAULT '[]'
        )
        """,
        """
        CREATE TABLE tokens (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            expires_at TEXT,
            last_used_at TEXT,
            revoked_at TEXT
        )
        """,
    )
