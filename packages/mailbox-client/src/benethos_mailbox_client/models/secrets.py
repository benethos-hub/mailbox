"""A secret the service shows once, kept out of every line."""

from __future__ import annotations


class Secret:
    """A secret the service shows once, e.g. a webhook's signing secret:
    kept out of ``repr`` and ``str`` so it reaches no log by accident, read
    with ``get_secret_value()``."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def get_secret_value(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "Secret('**********')"

    def __str__(self) -> str:
        return "**********"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Secret) and other._value == self._value

    def __hash__(self) -> int:
        return hash(self._value)
