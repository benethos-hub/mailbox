"""The clocks the tests of the storage move by hand."""

from __future__ import annotations


class Seconds:
    """A clock in seconds a test moves by hand."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now
