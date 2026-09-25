"""What a submitted form can be wrong about, said in one way."""

from __future__ import annotations

from pydantic import ValidationError


class FormError(ValueError):
    """What the form holds is not what the domain takes yet. ``message``
    reads like a domain error's, so a page shows either the same way."""

    @property
    def message(self) -> str:
        return str(self)


def first_problem(exc: ValidationError) -> str:
    """The first thing a model refused, as ``field: reason``."""
    problem = exc.errors()[0]
    where = ".".join(str(part) for part in problem["loc"])
    reason = str(problem["msg"]).removeprefix("Value error, ")
    return f"{where}: {reason}" if where else reason
