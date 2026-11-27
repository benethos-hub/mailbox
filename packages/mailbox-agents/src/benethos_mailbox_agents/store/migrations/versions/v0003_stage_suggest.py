"""The middle stage is called suggest since 2026-11-27, keyword before.

A row of ``actions`` and an item of ``open_items`` name the stage they
were recorded in, and the runtime compares that word with the stage of
the process: an action recorded only is not recorded again in the same
stage, and the keyword of an item is not tried again. With the old word
in the file and the new one in the process both would happen once more.
So the old word is written as the new one. The column
``keyword_recorded_stage`` keeps its name: it means the keyword of the
item, not the stage.
"""

from __future__ import annotations

from ..migration import Migration

__all__ = ["V0003StageSuggest"]


class V0003StageSuggest(Migration):
    version = 3
    statements = (
        """
            UPDATE actions SET stage = 'suggest' WHERE stage = 'keyword'
        """,
        """
            UPDATE open_items SET keyword_recorded_stage = 'suggest'
            WHERE keyword_recorded_stage = 'keyword'
        """,
    )
