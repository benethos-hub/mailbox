"""The process of one agent: its start, its state file, its metrics, its
stop."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from ..activity import Activity


@dataclass(frozen=True, slots=True, kw_only=True)
class Started(Activity):
    name: ClassVar[str] = "started"

    version: str
    stage: str

    def says(self) -> str:
        return f"started version {self.version} in stage {self.stage}"


@dataclass(frozen=True, slots=True, kw_only=True)
class Stopped(Activity):
    name: ClassVar[str] = "stopped"

    reason: str

    def says(self) -> str:
        return "stopped"

    def why(self) -> str | None:
        return self.reason


@dataclass(frozen=True, slots=True, kw_only=True)
class Migrated(Activity):
    """The state file was made, or brought from schema ``before`` to
    ``after``. The notes are the steps' own, words of code."""

    name: ClassVar[str] = "migrated"

    before: int
    after: int
    notes: tuple[str, ...]

    def says(self) -> str:
        if self.before == 0:
            return f"made its state file at schema {self.after}"
        return f"migrated its state file from schema {self.before} to {self.after}"

    def why(self) -> str | None:
        return ", ".join(self.notes) or None


@dataclass(frozen=True, slots=True, kw_only=True)
class MetricsServing(Activity):
    name: ClassVar[str] = "metrics_serving"

    port: int

    def says(self) -> str:
        return f"began serving metrics on port {self.port}"


@dataclass(frozen=True, slots=True, kw_only=True)
class A2AServing(Activity):
    name: ClassVar[str] = "a2a_serving"

    port: int

    def says(self) -> str:
        return f"began serving peers over A2A on port {self.port}"


@dataclass(frozen=True, slots=True, kw_only=True)
class CockpitServing(Activity):
    name: ClassVar[str] = "cockpit_serving"

    port: int
    named: bool

    def says(self) -> str:
        return f"began serving its pages on port {self.port}"

    def why(self) -> str | None:
        if self.named:
            return None
        return "ids only, as no token of the mailbox service is set"
