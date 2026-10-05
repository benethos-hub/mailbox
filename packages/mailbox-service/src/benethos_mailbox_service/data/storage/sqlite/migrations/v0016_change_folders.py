"""Schema 16: the change log keeps the folder of each change, so a grant
narrowed to folders hears only of its folders (PERMISSIONS.md 8.5).
Changes logged before have none.
"""

from __future__ import annotations

from .step import Migration

MIGRATION = Migration(
    [
        "ALTER TABLE changes ADD COLUMN folder_id TEXT",
    ],
)
