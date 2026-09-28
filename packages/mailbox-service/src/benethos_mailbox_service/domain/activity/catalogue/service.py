"""The service itself: recovery key, log page, backups, discovery
(docs/LOGGING.md 5.8)."""

from __future__ import annotations

from dataclasses import dataclass

from ..base import Activity


@dataclass(frozen=True, kw_only=True)
class RecoveryKeyShown(Activity):
    """The master key written out went to a person's screen."""

    def says(self) -> str:
        return "was shown the recovery key in the UI"
