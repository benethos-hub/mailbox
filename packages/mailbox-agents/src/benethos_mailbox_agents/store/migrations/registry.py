"""The steps of the schema, in their order."""

from __future__ import annotations

from .migration import Migration

__all__ = ["MigrationRegistry"]


class MigrationRegistry:
    """The migrations of a state file. Step ``n`` stands at place ``n``,
    which is checked when the registry is made, so a gap or a step at the
    wrong place stops the program before it touches a file."""

    def __init__(self, *steps: Migration) -> None:
        for number, step in enumerate(steps, 1):
            if step.version != number:
                raise ValueError(
                    f"{type(step).__name__} says version {step.version} "
                    f"but stands at {number}"
                )
        self._steps = steps

    @property
    def schema_version(self) -> int:
        """The version a file has once every step ran."""
        return len(self._steps)

    def pending(self, current: int) -> tuple[Migration, ...]:
        """The steps a file at ``current`` still lacks, in order."""
        return self._steps[current:]

    def step(self, version: int) -> Migration:
        """The step that leads to ``version``."""
        if not 1 <= version <= len(self._steps):
            raise ValueError(f"there is no migration to schema {version}")
        return self._steps[version - 1]
