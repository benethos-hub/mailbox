"""The schema of a state file, as numbered migrations.

Each step is a class ``VNNNN<Subject>`` of :class:`Migration` in its own
module ``versions/vNNNN_<subject>.py``, listed in ``MIGRATIONS`` at its
number. A file's ``user_version`` says how many have run. **A migration is
never changed once released**: ``RELEASED`` in
``packages/mailbox-agents/tests/store/test_store.py`` holds the fingerprint of each
released step. A change of the schema is a new step at the end.
docs/mailbox-agents/concept/state.md names the tables.
"""

from __future__ import annotations

from .migration import Migration
from .registry import MigrationRegistry
from .versions.v0001_state_file import V0001StateFile
from .versions.v0002_keyword_recorded_stage import V0002KeywordRecordedStage

__all__ = ["MIGRATIONS", "SCHEMA_VERSION", "Migration", "MigrationRegistry"]

MIGRATIONS = MigrationRegistry(
    V0001StateFile(),
    V0002KeywordRecordedStage(),
)
SCHEMA_VERSION = MIGRATIONS.schema_version
