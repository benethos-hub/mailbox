"""The stage in which the keyword of an open item was recorded without
being set, so the stage shadow records an item once and a later stage
that allows the keyword sets it.
"""

from __future__ import annotations

from ..migration import Migration

__all__ = ["V0002KeywordRecordedStage"]


class V0002KeywordRecordedStage(Migration):
    version = 2
    statements = (
        """
            ALTER TABLE open_items ADD COLUMN keyword_recorded_stage TEXT
        """,
    )
