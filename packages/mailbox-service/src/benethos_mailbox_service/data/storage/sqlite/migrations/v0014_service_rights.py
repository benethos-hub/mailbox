"""Schema 14: users and roles get a list of rights of the service, beside
their grants (PERMISSIONS.md 8.1). Schema 15 fills it.
"""

from __future__ import annotations

from .step import Migration

MIGRATION = Migration(
    [
        "ALTER TABLE users ADD COLUMN service TEXT NOT NULL DEFAULT '[]'",
        "ALTER TABLE roles ADD COLUMN service TEXT NOT NULL DEFAULT '[]'",
    ],
)
