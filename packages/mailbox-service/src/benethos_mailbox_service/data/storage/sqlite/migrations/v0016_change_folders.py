"""Schema 16: the change log keeps the folder of each change, so a grant
narrowed to folders hears only of its folders (PERMISSIONS.md 8.5).
Changes logged before have none.
"""

from __future__ import annotations

from .migration import Migration


class ChangeFolders(Migration):
    version = 16
    statements = ("ALTER TABLE changes ADD COLUMN folder_id TEXT",)
